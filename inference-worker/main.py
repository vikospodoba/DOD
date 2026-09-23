from __future__ import annotations

import json
import os
import socketserver
import struct
import subprocess
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from typing import Deque

from processor import FrameProcessor, create_processor, required_model_files

try:
    import pynvml
except ImportError:  # pragma: no cover
    pynvml = None


HOST = "0.0.0.0"
PORT = 8001
FRAME_PORT = int(os.environ.get("DOD_WORKER_FRAME_PORT", "8002"))
MAX_FRAME_MESSAGE_BYTES = int(os.environ.get("DOD_WORKER_MAX_FRAME_MESSAGE_BYTES", str(16 * 1024 * 1024)))
READY = False
MODEL_DIR = Path(os.environ.get("DOD_MODEL_DIR", "models/deeplivecam"))
CHARACTERS_DIR = Path(os.environ.get("DOD_CHARACTERS_DIR", "characters"))
TEMP_DIR = Path(os.environ.get("DOD_WORKER_TEMP_DIR", "/tmp/dod-worker"))
INFERENCE_MODE = os.environ.get("DOD_INFERENCE_MODE", "stub")
VALID_CHARACTERS = set(
    character_id.strip()
    for character_id in os.environ.get("DOD_CHARACTER_IDS", "default-human").split(",")
    if character_id.strip()
)
SELECTED_CHARACTER_ID = os.environ.get("DOD_DEFAULT_CHARACTER_ID", "default-human")
INFERENCE_TIMES_MS: Deque[float] = deque(maxlen=120)
FRAME_TIMES: Deque[float] = deque(maxlen=120)
PROCESSOR: FrameProcessor | None = None
STARTUP_ERRORS: list[str] = []


class WorkerHandler(BaseHTTPRequestHandler):
    server_version = "DodInferenceWorker/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self.write_json(
                HTTPStatus.OK,
                {
                    "status": "ok" if READY else "model_not_ready",
                    "ready": READY,
                    "fps": current_fps(),
                    "inferenceMs": average_inference_ms(),
                    "gpuMemoryUsedMb": gpu_memory_used_mb(),
                    "mode": INFERENCE_MODE,
                    "startupErrors": STARTUP_ERRORS,
                },
            )
            return

        if self.path == "/ready":
            self.write_json(HTTPStatus.OK, {"ready": READY})
            return

        self.write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/prepare-character":
            self.handle_character_command("prepare")
            return

        if path == "/v1/select-character":
            self.handle_character_command("select")
            return

        self.write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def handle_character_command(self, command: str) -> None:
        global SELECTED_CHARACTER_ID
        if not READY or PROCESSOR is None:
            self.write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "status": "model_not_ready",
                    "ready": READY,
                    "selectedCharacterId": SELECTED_CHARACTER_ID,
                },
            )
            return

        payload = self.read_json_body()
        character_id = str(payload.get("characterId", ""))
        if command == "prepare":
            status = PROCESSOR.prepare_character(character_id)
        else:
            status = PROCESSOR.select_character(character_id)
            if status == "ok":
                SELECTED_CHARACTER_ID = character_id

        http_status = HTTPStatus.OK if status == "ok" else HTTPStatus.BAD_REQUEST
        self.write_json(
            http_status,
            {
                "status": status,
                "ready": READY,
                "characterId": character_id,
                "selectedCharacterId": SELECTED_CHARACTER_ID,
            },
        )

    def read_json_body(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        body = self.rfile.read(content_length)
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def log_message(self, format: str, *args: object) -> None:
        print("%s - %s" % (self.log_date_time_string(), format % args), flush=True)

    def write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FrameStreamHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        while True:
            length_bytes = read_exact(self.request, 4)
            if length_bytes is None:
                return

            message_length = struct.unpack(">I", length_bytes)[0]
            if message_length <= 0 or message_length > MAX_FRAME_MESSAGE_BYTES:
                return

            payload = read_exact(self.request, message_length)
            if payload is None:
                return

            try:
                metadata, frame = unpack_binary_frame(payload)
                character_id = str(metadata.get("characterId") or SELECTED_CHARACTER_ID)
                many_faces = bool(metadata.get("manyFaces"))
                status, output_frame, elapsed_ms = process_frame_bytes(character_id, frame, many_faces)
                response = pack_binary_frame(
                    {
                        "status": status,
                        "characterId": character_id,
                        "sequence": int(metadata.get("sequence") or 0),
                        "capturedAtEpochMs": int(metadata.get("capturedAtEpochMs") or 0),
                        "inferenceMs": elapsed_ms,
                    },
                    output_frame,
                )
                self.request.sendall(struct.pack(">I", len(response)) + response)
            except Exception as exc:
                print(f"Frame stream error: {exc}", flush=True)
                return


class ThreadingFrameServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def read_exact(stream, byte_count: int) -> bytes | None:
    chunks = []
    remaining = byte_count
    while remaining > 0:
        chunk = stream.recv(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def unpack_binary_frame(payload: bytes) -> tuple[dict[str, object], bytes]:
    if len(payload) < 4:
        raise ValueError("frame payload is shorter than metadata length prefix")
    header_length = struct.unpack(">I", payload[:4])[0]
    if header_length <= 0 or len(payload) < 4 + header_length:
        raise ValueError("invalid frame metadata length")
    metadata = json.loads(payload[4:4 + header_length].decode("utf-8"))
    return metadata, payload[4 + header_length:]


def pack_binary_frame(metadata: dict[str, object], frame: bytes) -> bytes:
    header = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    return struct.pack(">I", len(header)) + header + frame


def process_frame_bytes(character_id: str, frame: bytes, many_faces: bool) -> tuple[str, bytes, int]:
    started = time.perf_counter()
    if not READY or PROCESSOR is None:
        status = "model_not_ready"
        output_frame = frame
    elif character_id not in VALID_CHARACTERS:
        status = "invalid_character"
        output_frame = frame
    elif not frame:
        status = "processing_error"
        output_frame = frame
    else:
        result = PROCESSOR.process(character_id, frame, many_faces)
        status = result.status
        output_frame = result.image_bytes

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    INFERENCE_TIMES_MS.append(float(elapsed_ms))
    FRAME_TIMES.append(time.perf_counter())
    return status, output_frame, elapsed_ms


def startup() -> None:
    global PROCESSOR, READY, STARTUP_ERRORS
    if pynvml is not None:
        try:
            pynvml.nvmlInit()
        except Exception:
            pass

    if INFERENCE_MODE == "deep_live_cam":
        missing_files = required_model_files(MODEL_DIR)
        if missing_files:
            print(f"Model directory is incomplete: {MODEL_DIR}", flush=True)
            for relative_path in missing_files:
                print(f"Missing model file: {relative_path}", flush=True)
            READY = False
            STARTUP_ERRORS = missing_files
            return

    PROCESSOR = create_processor(INFERENCE_MODE, MODEL_DIR, CHARACTERS_DIR, VALID_CHARACTERS, TEMP_DIR)
    READY, STARTUP_ERRORS = PROCESSOR.prepare()
    if not READY:
        for error in STARTUP_ERRORS:
            print(error, flush=True)


def current_fps() -> float:
    if len(FRAME_TIMES) < 2:
        return 0.0
    elapsed = FRAME_TIMES[-1] - FRAME_TIMES[0]
    if elapsed <= 0:
        return 0.0
    return round((len(FRAME_TIMES) - 1) / elapsed, 2)


def average_inference_ms() -> float:
    if not INFERENCE_TIMES_MS:
        return 0.0
    return round(sum(INFERENCE_TIMES_MS) / len(INFERENCE_TIMES_MS), 2)


def gpu_memory_used_mb() -> int:
    if pynvml is None:
        return gpu_memory_used_mb_from_nvidia_smi()
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return int(info.used / 1024 / 1024)
    except Exception:
        return gpu_memory_used_mb_from_nvidia_smi()


def gpu_memory_used_mb_from_nvidia_smi() -> int:
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        values = [int(line.strip()) for line in output.splitlines() if line.strip().isdigit()]
        return sum(values)
    except Exception:
        return 0


if __name__ == "__main__":
    startup()
    frame_server = ThreadingFrameServer((HOST, FRAME_PORT), FrameStreamHandler)
    threading.Thread(target=frame_server.serve_forever, name="frame-stream-server", daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), WorkerHandler)
    print(f"Inference worker listening on {HOST}:{PORT}", flush=True)
    print(f"Inference frame stream listening on {HOST}:{FRAME_PORT}", flush=True)
    print(f"Inference mode: {INFERENCE_MODE}", flush=True)
    print(f"Model directory: {MODEL_DIR.resolve()}", flush=True)
    print(f"Characters directory: {CHARACTERS_DIR.resolve()}", flush=True)
    server.serve_forever()

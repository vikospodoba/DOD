from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame

from processor import FrameProcessor, create_processor, required_model_files


ROOT_DIR = Path(__file__).resolve().parents[1]
DEEP_LIVE_CAM_DIR = ROOT_DIR / "experiments" / "Deep-Live-Cam"
MODEL_DIR = Path(os.environ.get("DOD_MODEL_DIR", DEEP_LIVE_CAM_DIR / "models"))
CHARACTERS_DIR = Path(os.environ.get("DOD_CHARACTERS_DIR", ROOT_DIR / "characters"))
TEMP_DIR = Path(os.environ.get("DOD_WORKER_TEMP_DIR", ROOT_DIR / "logs" / "webrtc-temp"))
STATIC_DIR = Path(__file__).resolve().parent / "webrtc-static"

PROCESSOR: FrameProcessor | None = None
READY = False
STARTUP_ERRORS: list[str] = []
PEERS: set[RTCPeerConnection] = set()
INFERENCE_TIMES_MS: deque[float] = deque(maxlen=120)
FRAME_TIMES: deque[float] = deque(maxlen=120)


class ProcessedVideoTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self, source_track: VideoStreamTrack, character_id: str, many_faces: bool):
        super().__init__()
        self.source_track = source_track
        self.character_id = character_id
        self.many_faces = many_faces
        self._settings_lock = threading.Lock()

    def set_settings(self, character_id: str, many_faces: bool) -> None:
        with self._settings_lock:
            self.character_id = character_id
            self.many_faces = many_faces

    def get_settings(self) -> tuple[str, bool]:
        with self._settings_lock:
            return self.character_id, self.many_faces

    async def recv(self) -> VideoFrame:
        frame = await self.source_track.recv()
        if PROCESSOR is None or not READY:
            return frame

        started = time.perf_counter()
        bgr = frame.to_ndarray(format="bgr24")
        character_id, many_faces = self.get_settings()
        result = await asyncio.to_thread(PROCESSOR.process_array, character_id, bgr, many_faces)
        elapsed_ms = (time.perf_counter() - started) * 1000
        INFERENCE_TIMES_MS.append(elapsed_ms)
        FRAME_TIMES.append(time.perf_counter())

        output = result.frame if result.status == "ok" else bgr
        new_frame = VideoFrame.from_ndarray(output, format="bgr24")
        new_frame.pts = frame.pts
        new_frame.time_base = frame.time_base
        return new_frame


def load_character_ids() -> set[str]:
    manifest_path = CHARACTERS_DIR / "manifest.json"
    if not manifest_path.exists():
        return {"default-human"}
    with manifest_path.open("r", encoding="utf-8") as handle:
        return {str(item["id"]) for item in json.load(handle) if item.get("id")}


def load_characters() -> list[dict[str, Any]]:
    manifest_path = CHARACTERS_DIR / "manifest.json"
    if not manifest_path.exists():
        return []
    with manifest_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def startup() -> None:
    global PROCESSOR, READY, STARTUP_ERRORS

    os.environ.setdefault("DOD_INFERENCE_MODE", "deep_live_cam")
    os.environ.setdefault("DOD_DEEP_LIVE_CAM_DIR", str(DEEP_LIVE_CAM_DIR))
    os.environ.setdefault("DOD_MODEL_DIR", str(MODEL_DIR))
    os.environ.setdefault("DOD_CHARACTERS_DIR", str(CHARACTERS_DIR))
    os.environ.setdefault("DOD_EXECUTION_PROVIDERS", "cuda,cpu")
    os.environ.setdefault("DOD_EXECUTION_THREADS", "1")
    os.environ.setdefault("DOD_DISABLE_CUDA_GRAPH", "true")
    os.environ.setdefault("DOD_CUDA_GPU_MEM_LIMIT_MB", "12288")

    missing_files = required_model_files(MODEL_DIR)
    if missing_files:
        READY = False
        STARTUP_ERRORS = missing_files
        return

    valid_character_ids = load_character_ids()
    PROCESSOR = create_processor("deep_live_cam", MODEL_DIR, CHARACTERS_DIR, valid_character_ids, TEMP_DIR)
    READY, STARTUP_ERRORS = PROCESSOR.prepare()
    if READY:
        default_character_id = os.environ.get("DOD_DEFAULT_CHARACTER_ID", next(iter(valid_character_ids)))
        if default_character_id in valid_character_ids:
            PROCESSOR.prepare_character(default_character_id)


async def index(_: web.Request) -> web.Response:
    return web.FileResponse(STATIC_DIR / "index.html")


async def health(_: web.Request) -> web.Response:
    return web.json_response(
        {
            "ready": READY,
            "startupErrors": STARTUP_ERRORS,
            "fps": current_fps(),
            "inferenceMs": average_inference_ms(),
        }
    )


async def characters(_: web.Request) -> web.Response:
    return web.json_response(load_characters())


async def offer(request: web.Request) -> web.Response:
    if PROCESSOR is None or not READY:
        return web.json_response({"error": "model_not_ready", "startupErrors": STARTUP_ERRORS}, status=503)

    payload = await request.json()
    character_id = str(payload.get("characterId", os.environ.get("DOD_DEFAULT_CHARACTER_ID", "default-human")))
    many_faces = bool(payload.get("manyFaces", False))

    status = PROCESSOR.prepare_character(character_id)
    if status != "ok":
        return web.json_response({"error": status}, status=400)

    pc = RTCPeerConnection()
    PEERS.add(pc)
    processed_track: ProcessedVideoTrack | None = None

    @pc.on("connectionstatechange")
    async def on_connectionstatechange() -> None:
        print(f"[webrtc] connection state: {pc.connectionState}", flush=True)
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            PEERS.discard(pc)

    @pc.on("track")
    def on_track(track: VideoStreamTrack) -> None:
        nonlocal processed_track
        print(f"[webrtc] incoming track: {track.kind}", flush=True)
        if track.kind == "video":
            processed_track = ProcessedVideoTrack(track, character_id, many_faces)
            pc.addTrack(processed_track)

    @pc.on("datachannel")
    def on_datachannel(channel: Any) -> None:
        print(f"[webrtc] data channel: {channel.label}", flush=True)

        @channel.on("message")
        def on_message(message: str | bytes) -> None:
            asyncio.create_task(handle_control_message(message, channel))

    async def handle_control_message(message: str | bytes, channel: Any) -> None:
        nonlocal character_id, many_faces, processed_track
        if isinstance(message, bytes):
            message = message.decode("utf-8")

        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            channel.send(json.dumps({"type": "settings", "status": "invalid_json"}))
            return

        if payload.get("type") != "settings":
            return

        next_character_id = str(payload.get("characterId", character_id))
        next_many_faces = bool(payload.get("manyFaces", many_faces))
        status = await asyncio.to_thread(PROCESSOR.prepare_character, next_character_id)
        if status != "ok":
            channel.send(json.dumps({"type": "settings", "status": status, "characterId": next_character_id}))
            return

        character_id = next_character_id
        many_faces = next_many_faces
        if processed_track is not None:
            processed_track.set_settings(character_id, many_faces)
        channel.send(
            json.dumps(
                {
                    "type": "settings",
                    "status": "ok",
                    "characterId": character_id,
                    "manyFaces": many_faces,
                }
            )
        )

    offer_description = RTCSessionDescription(sdp=payload["sdp"], type=payload["type"])
    await pc.setRemoteDescription(offer_description)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.json_response({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})


async def on_shutdown(_: web.Application) -> None:
    await asyncio.gather(*(pc.close() for pc in PEERS), return_exceptions=True)
    PEERS.clear()


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


def create_app() -> web.Application:
    startup()
    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/characters", characters)
    app.router.add_post("/offer", offer)
    app.router.add_static("/static", STATIC_DIR)
    app.router.add_static("/characters", CHARACTERS_DIR)
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("DOD_WEBRTC_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DOD_WEBRTC_PORT", "8088")))
    args = parser.parse_args()

    print(f"[webrtc] listening on http://{args.host}:{args.port}", flush=True)
    web.run_app(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()

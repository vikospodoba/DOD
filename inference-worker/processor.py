from __future__ import annotations

import ctypes
import glob
import importlib
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class ProcessingResult:
    status: str
    image_bytes: bytes


@dataclass(frozen=True)
class ProcessingArrayResult:
    status: str
    frame: Any


class FrameProcessor:
    def prepare(self) -> tuple[bool, list[str]]:
        raise NotImplementedError

    def prepare_character(self, character_id: str) -> str:
        raise NotImplementedError

    def select_character(self, character_id: str) -> str:
        raise NotImplementedError

    def process(self, character_id: str, frame: bytes, many_faces: bool = False) -> ProcessingResult:
        raise NotImplementedError

    def process_array(self, character_id: str, frame: Any, many_faces: bool = False) -> ProcessingArrayResult:
        raise NotImplementedError


class StubFrameProcessor(FrameProcessor):
    def __init__(self, characters_dir: Path, valid_character_ids: set[str]):
        self.characters_dir = characters_dir
        self.valid_character_ids = valid_character_ids

    def prepare(self) -> tuple[bool, list[str]]:
        return True, []

    def prepare_character(self, character_id: str) -> str:
        if character_id not in self.valid_character_ids:
            return "invalid_character"
        if self._find_character_image(character_id) is None:
            return "invalid_character"
        return "ok"

    def select_character(self, character_id: str) -> str:
        return self.prepare_character(character_id)

    def process(self, character_id: str, frame: bytes, many_faces: bool = False) -> ProcessingResult:
        if character_id not in self.valid_character_ids:
            return ProcessingResult("invalid_character", frame)
        if not frame:
            return ProcessingResult("processing_error", frame)
        return ProcessingResult("ok", frame)

    def process_array(self, character_id: str, frame: Any, many_faces: bool = False) -> ProcessingArrayResult:
        if character_id not in self.valid_character_ids:
            return ProcessingArrayResult("invalid_character", frame)
        if frame is None:
            return ProcessingArrayResult("processing_error", frame)
        return ProcessingArrayResult("ok", frame)

    def _find_character_image(self, character_id: str) -> Path | None:
        return find_character_image(self.characters_dir, character_id)


class DeepLiveCamFrameProcessor(FrameProcessor):
    def __init__(self, model_dir: Path, characters_dir: Path, valid_character_ids: set[str]):
        self.model_dir = model_dir
        self.characters_dir = characters_dir
        self.valid_character_ids = valid_character_ids
        self.deep_live_cam_dir = Path(
            os.environ.get(
                "DOD_DEEP_LIVE_CAM_DIR",
                Path(__file__).resolve().parents[1] / "experiments" / "Deep-Live-Cam",
            )
        )
        self._lock = threading.RLock()
        self._source_faces: dict[str, Any] = {}
        self._cv2: Any | None = None
        self._np: Any | None = None
        self._modules_globals: Any | None = None
        self._face_analyser: Any | None = None
        self._target_face_detector: Any | None = None
        self._many_faces_detector: Any | None = None
        self._face_swapper: Any | None = None
        self._face_enhancer: Any | None = None
        self._imread_unicode: Any | None = None
        self._selected_face_bbox: list[float] | None = None
        self._pending_face_bbox: list[float] | None = None
        self._pending_face_since: float | None = None
        self._selected_face_lost_since: float | None = None
        self._single_face_frame_index = 0
        self._cached_target_faces: Any | None = None
        self._face_detection_interval = max(1, env_int("DOD_FACE_DETECTION_INTERVAL", 1))
        self._switch_area_ratio = float(os.environ.get("DOD_FACE_SWITCH_AREA_RATIO", "1.25"))
        self._switch_hold_ms = int(os.environ.get("DOD_FACE_SWITCH_HOLD_MS", "500"))
        self._lost_hold_ms = int(os.environ.get("DOD_FACE_LOST_HOLD_MS", "300"))
        self._face_enhancer_mode = normalize_face_enhancer_mode(os.environ.get("DOD_FACE_ENHANCER", "none"))

    def prepare(self) -> tuple[bool, list[str]]:
        with self._lock:
            errors = self._validate_runtime_paths()
            if errors:
                return False, errors

            try:
                self._register_deep_live_cam_runtime()
                import cv2
                import numpy as np
                import modules.globals as modules_globals
                from modules import imread_unicode
                from modules.face_analyser import detect_many_faces_fast, detect_one_face_fast, get_one_face
                from modules.processors.frame import face_swapper

                self._cv2 = cv2
                self._np = np
                self._modules_globals = modules_globals
                self._face_analyser = get_one_face
                self._target_face_detector = detect_one_face_fast
                self._many_faces_detector = detect_many_faces_fast
                self._face_swapper = face_swapper
                self._imread_unicode = imread_unicode

                self._configure_deep_live_cam_globals()
                face_swapper.models_dir = str(self.model_dir.resolve())
                if not face_swapper.pre_start():
                    return False, ["Deep-Live-Cam face swapper model failed to start."]

                enhancer_error = self._configure_face_enhancer()
                if enhancer_error is not None:
                    return False, [enhancer_error]

                return True, []
            except Exception as exc:
                return False, [f"Deep-Live-Cam startup failed: {exc}"]

    def prepare_character(self, character_id: str) -> str:
        if character_id not in self.valid_character_ids:
            return "invalid_character"

        with self._lock:
            try:
                if character_id in self._source_faces:
                    return "ok"

                image_path = find_character_image(self.characters_dir, character_id)
                if image_path is None:
                    return "invalid_character"

                if self._imread_unicode is None or self._face_analyser is None:
                    return "model_not_ready"

                source_image = self._imread_unicode(str(image_path))
                if source_image is None:
                    return "invalid_character"

                source_face = self._face_analyser(source_image)
                if source_face is None:
                    return "invalid_character"

                self._source_faces[character_id] = source_face
                return "ok"
            except Exception:
                traceback.print_exc()
                return "invalid_character"

    def select_character(self, character_id: str) -> str:
        return self.prepare_character(character_id)

    def process(self, character_id: str, frame: bytes, many_faces: bool = False) -> ProcessingResult:
        if character_id not in self.valid_character_ids:
            return ProcessingResult("invalid_character", frame)
        if not frame:
            return ProcessingResult("processing_error", frame)

        with self._lock:
            if self._cv2 is None or self._np is None or self._modules_globals is None or self._face_swapper is None:
                return ProcessingResult("model_not_ready", frame)

            if character_id not in self._source_faces and self.prepare_character(character_id) != "ok":
                return ProcessingResult("invalid_character", frame)

            try:
                data = self._np.frombuffer(frame, dtype=self._np.uint8)
                input_frame = self._cv2.imdecode(data, self._cv2.IMREAD_COLOR)
                if input_frame is None:
                    return ProcessingResult("processing_error", frame)

                result = self._process_array_locked(character_id, input_frame, many_faces)
                if result.status != "ok":
                    return ProcessingResult(result.status, frame)

                ok, encoded = self._cv2.imencode(
                    ".jpg",
                    result.frame,
                    [int(self._cv2.IMWRITE_JPEG_QUALITY), 92],
                )
                if not ok:
                    return ProcessingResult("processing_error", frame)
                return ProcessingResult("ok", encoded.tobytes())
            except Exception:
                traceback.print_exc()
                return ProcessingResult("processing_error", frame)

    def process_array(self, character_id: str, frame: Any, many_faces: bool = False) -> ProcessingArrayResult:
        if character_id not in self.valid_character_ids:
            return ProcessingArrayResult("invalid_character", frame)
        if frame is None:
            return ProcessingArrayResult("processing_error", frame)

        with self._lock:
            if self._cv2 is None or self._np is None or self._modules_globals is None or self._face_swapper is None:
                return ProcessingArrayResult("model_not_ready", frame)

            if character_id not in self._source_faces and self.prepare_character(character_id) != "ok":
                return ProcessingArrayResult("invalid_character", frame)

            try:
                return self._process_array_locked(character_id, frame, many_faces)
            except Exception:
                traceback.print_exc()
                return ProcessingArrayResult("processing_error", frame)

    def _process_array_locked(self, character_id: str, input_frame: Any, many_faces: bool) -> ProcessingArrayResult:
        assert self._modules_globals is not None
        assert self._face_swapper is not None

        self._modules_globals.many_faces = False
        if many_faces:
            if self._many_faces_detector is None:
                return ProcessingArrayResult("model_not_ready", input_frame)

            target_faces = self._many_faces_detector(input_frame)
            if not target_faces:
                return ProcessingArrayResult("no_face", input_frame)

            output_frame = input_frame
            for target_face in target_faces:
                output_frame = self._face_swapper.process_frame(
                    self._source_faces[character_id],
                    output_frame,
                    target_face,
                )
                if output_frame is None:
                    return ProcessingArrayResult("processing_error", input_frame)
            output_frame = self._enhance_frame_if_enabled(output_frame, list(target_faces))
            return ProcessingArrayResult("ok", output_frame)

        if self._many_faces_detector is None:
            return ProcessingArrayResult("model_not_ready", input_frame)

        target_faces = self._detect_single_face_targets(input_frame)
        target_face = self._select_stable_target_face(target_faces)
        if target_face is None:
            return ProcessingArrayResult("no_face", input_frame)

        output_frame = self._face_swapper.process_frame(
            self._source_faces[character_id],
            input_frame,
            target_face,
        )
        if output_frame is None:
            return ProcessingArrayResult("processing_error", input_frame)
        output_frame = self._enhance_frame_if_enabled(output_frame, [target_face])
        return ProcessingArrayResult("ok", output_frame)

    def _detect_single_face_targets(self, input_frame: Any) -> Any:
        self._single_face_frame_index += 1
        should_detect = (
            self._cached_target_faces is None
            or self._single_face_frame_index % self._face_detection_interval == 1
        )
        if should_detect:
            self._cached_target_faces = self._many_faces_detector(input_frame)
        return self._cached_target_faces

    def _select_stable_target_face(self, faces: Any) -> Any | None:
        now = time.monotonic()
        if not faces:
            if self._selected_face_lost_since is None:
                self._selected_face_lost_since = now
            if elapsed_ms(self._selected_face_lost_since, now) >= self._lost_hold_ms:
                self._clear_face_tracking()
            return None

        largest_face = max(faces, key=self._face_area)
        if self._selected_face_bbox is None:
            self._set_selected_face(largest_face)
            return largest_face

        current_face = self._find_matching_face(faces, self._selected_face_bbox)
        if current_face is None:
            if self._selected_face_lost_since is None:
                self._selected_face_lost_since = now
                return None
            if elapsed_ms(self._selected_face_lost_since, now) < self._lost_hold_ms:
                return None
            self._set_selected_face(largest_face)
            return largest_face

        self._selected_face_lost_since = None
        current_area = self._face_area(current_face)
        largest_area = self._face_area(largest_face)
        if self._faces_overlap(current_face, largest_face) or largest_area < current_area * self._switch_area_ratio:
            self._pending_face_bbox = None
            self._pending_face_since = None
            self._set_selected_face(current_face)
            return current_face

        largest_bbox = self._face_bbox(largest_face)
        if self._pending_face_bbox is None or not bboxes_overlap(self._pending_face_bbox, largest_bbox):
            self._pending_face_bbox = largest_bbox
            self._pending_face_since = now
            self._set_selected_face(current_face)
            return current_face

        if self._pending_face_since is not None and elapsed_ms(self._pending_face_since, now) >= self._switch_hold_ms:
            self._set_selected_face(largest_face)
            self._pending_face_bbox = None
            self._pending_face_since = None
            return largest_face

        self._set_selected_face(current_face)
        return current_face

    def _set_selected_face(self, face: Any) -> None:
        self._selected_face_bbox = self._face_bbox(face)
        self._selected_face_lost_since = None

    def _clear_face_tracking(self) -> None:
        self._selected_face_bbox = None
        self._pending_face_bbox = None
        self._pending_face_since = None
        self._selected_face_lost_since = None

    def _find_matching_face(self, faces: Any, bbox: list[float]) -> Any | None:
        matches = [(bbox_iou(self._face_bbox(face), bbox), face) for face in faces]
        best_iou, best_face = max(matches, key=lambda item: item[0])
        return best_face if best_iou >= 0.2 else None

    def _faces_overlap(self, first_face: Any, second_face: Any) -> bool:
        return bboxes_overlap(self._face_bbox(first_face), self._face_bbox(second_face))

    @staticmethod
    def _face_bbox(face: Any) -> list[float]:
        bbox = getattr(face, "bbox", None)
        if bbox is None and isinstance(face, dict):
            bbox = face.get("bbox")
        return [float(value) for value in bbox[:4]]

    def _face_area(self, face: Any) -> float:
        bbox = self._face_bbox(face)
        return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])

    def _validate_runtime_paths(self) -> list[str]:
        errors = []
        if not self.deep_live_cam_dir.exists():
            errors.append(f"Deep-Live-Cam directory not found: {self.deep_live_cam_dir}")
        if not (self.deep_live_cam_dir / "modules").exists():
            errors.append(f"Deep-Live-Cam modules directory not found: {self.deep_live_cam_dir / 'modules'}")
        errors.extend(f"Missing model file: {path}" for path in required_model_files(self.model_dir))
        return errors

    def _register_deep_live_cam_runtime(self) -> None:
        root = str(self.deep_live_cam_dir.resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
        os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")

        if sys.platform == "win32":
            site_packages = Path(sys.prefix) / "Lib" / "site-packages"
            candidate_dirs = []
            torch_lib = site_packages / "torch" / "lib"
            if torch_lib.is_dir():
                candidate_dirs.append(torch_lib)
            nvidia_dir = site_packages / "nvidia"
            if nvidia_dir.is_dir():
                for package_dir in nvidia_dir.iterdir():
                    bin_dir = package_dir / "bin"
                    if bin_dir.is_dir():
                        candidate_dirs.append(bin_dir)

            for directory in candidate_dirs:
                directory_value = str(directory)
                os.environ["PATH"] = directory_value + os.pathsep + os.environ["PATH"]
                try:
                    os.add_dll_directory(directory_value)
                except (AttributeError, OSError):
                    pass
        elif sys.platform.startswith("linux"):
            py_lib = f"python{sys.version_info.major}.{sys.version_info.minor}"
            site_packages_candidates = [
                Path(sys.prefix) / "lib" / py_lib / "site-packages",
                Path("/usr/local/lib") / py_lib / "site-packages",
            ]
            library_dirs = []
            for site_packages in site_packages_candidates:
                nvidia_dir = site_packages / "nvidia"
                if not nvidia_dir.is_dir():
                    continue
                library_dirs.extend(
                    package_dir / "lib"
                    for package_dir in nvidia_dir.iterdir()
                    if (package_dir / "lib").is_dir()
                )

            existing_ld_path = os.environ.get("LD_LIBRARY_PATH", "")
            for library_dir in library_dirs:
                library_dir_value = str(library_dir)
                if library_dir_value not in existing_ld_path.split(":"):
                    os.environ["LD_LIBRARY_PATH"] = (
                        library_dir_value + ":" + os.environ.get("LD_LIBRARY_PATH", "")
                    )
                for library_path in glob.glob(str(library_dir / "*.so*")):
                    try:
                        ctypes.CDLL(library_path, mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass

    def _configure_deep_live_cam_globals(self) -> None:
        assert self._modules_globals is not None

        globals_module = self._modules_globals
        globals_module.source_path = None
        globals_module.target_path = None
        globals_module.output_path = None
        globals_module.frame_processors = ["face_swapper"]
        globals_module.headless = True
        globals_module.keep_fps = False
        globals_module.keep_audio = False
        globals_module.keep_frames = False
        globals_module.many_faces = False
        globals_module.map_faces = False
        globals_module.poisson_blend = env_bool("DOD_POISSON_BLEND", False)
        globals_module.color_correction = env_bool("DOD_COLOR_CORRECTION", False)
        globals_module.nsfw_filter = False
        globals_module.mouth_mask_size = env_float("DOD_MOUTH_MASK_SIZE", 0.0)
        globals_module.mouth_mask = env_bool("DOD_MOUTH_MASK", globals_module.mouth_mask_size > 0.0)
        globals_module.show_mouth_mask_box = env_bool("DOD_SHOW_MOUTH_MASK_BOX", False)
        globals_module.fp_ui = {
            "face_enhancer": self._face_enhancer_mode == "gfpgan",
            "face_enhancer_gpen256": self._face_enhancer_mode == "gpen256",
            "face_enhancer_gpen512": self._face_enhancer_mode == "gpen512",
        }
        globals_module.max_memory = None
        globals_module.execution_providers = self._select_execution_providers()
        globals_module.execution_threads = int(os.environ.get("DOD_EXECUTION_THREADS", "2"))
        globals_module.opacity = clamp_float(env_float("DOD_OPACITY", 1.0), 0.0, 1.0)
        globals_module.sharpness = max(0.0, env_float("DOD_SHARPNESS", 0.0))

    def _configure_face_enhancer(self) -> str | None:
        if self._face_enhancer_mode == "none":
            return None

        module_name_by_mode = {
            "gfpgan": "face_enhancer",
            "gpen256": "face_enhancer_gpen256",
            "gpen512": "face_enhancer_gpen512",
        }
        model_file_by_mode = {
            "gfpgan": "gfpgan-1024.onnx",
            "gpen256": "GPEN-BFR-256.onnx",
            "gpen512": "GPEN-BFR-512.onnx",
        }
        module_name = module_name_by_mode[self._face_enhancer_mode]
        model_file = model_file_by_mode[self._face_enhancer_mode]
        model_path = self.model_dir / model_file
        if not model_path.exists():
            return (
                f"DOD_FACE_ENHANCER={self._face_enhancer_mode} requires local model file "
                f"{model_path}. Set DOD_FACE_ENHANCER=none or add the model file."
            )

        enhancer = importlib.import_module(f"modules.processors.frame.{module_name}")
        enhancer.models_dir = str(self.model_dir.resolve())
        self._face_enhancer = enhancer
        return None

    def _enhance_frame_if_enabled(self, frame: Any, target_faces: list[Any]) -> Any:
        if self._face_enhancer is None:
            return frame
        detected_faces = [face for face in target_faces if face is not None]
        try:
            return self._face_enhancer.process_frame(None, frame, detected_faces=detected_faces)
        except TypeError:
            return self._face_enhancer.process_frame(None, frame)
        except Exception:
            traceback.print_exc()
            return frame

    @staticmethod
    def _select_execution_providers() -> list[str]:
        import onnxruntime

        available = list(onnxruntime.get_available_providers())
        requested = [
            value.strip().lower()
            for value in os.environ.get("DOD_EXECUTION_PROVIDERS", "cuda,dml,openvino,cpu").split(",")
            if value.strip()
        ]
        aliases = {
            "cuda": "CUDAExecutionProvider",
            "dml": "DmlExecutionProvider",
            "directml": "DmlExecutionProvider",
            "openvino": "OpenVINOExecutionProvider",
            "cpu": "CPUExecutionProvider",
        }

        selected = []
        for item in requested:
            provider = aliases.get(item, item)
            if provider in available and provider not in selected:
                selected.append(provider)

        if "CPUExecutionProvider" in available and "CPUExecutionProvider" not in selected:
            selected.append("CPUExecutionProvider")
        return selected or available


def find_character_image(characters_dir: Path, character_id: str) -> Path | None:
    for suffix in IMAGE_SUFFIXES:
        candidate = characters_dir / f"{character_id}{suffix}"
        if candidate.exists():
            return candidate
    return None


def required_model_files(model_dir: Path) -> list[str]:
    if (model_dir / "inswapper_128_fp16.onnx").exists() or (model_dir / "inswapper_128.onnx").exists():
        return []
    return ["inswapper_128_fp16.onnx or inswapper_128.onnx"]


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def normalize_face_enhancer_mode(value: str | None) -> str:
    normalized = (value or "none").strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "none": "none",
        "off": "none",
        "false": "none",
        "0": "none",
        "gfpgan": "gfpgan",
        "gpen256": "gpen256",
        "gpen512": "gpen512",
    }
    return aliases.get(normalized, "none")


def elapsed_ms(started_at: float, now: float) -> int:
    return int((now - started_at) * 1000)


def bboxes_overlap(first: list[float], second: list[float]) -> bool:
    return bbox_iou(first, second) >= 0.2


def bbox_iou(first: list[float], second: list[float]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if intersection <= 0:
        return 0.0

    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def create_processor(
    mode: str,
    model_dir: Path,
    characters_dir: Path,
    valid_character_ids: set[str],
    temp_dir: Path,
) -> FrameProcessor:
    if mode == "deep_live_cam":
        return DeepLiveCamFrameProcessor(model_dir, characters_dir, valid_character_ids)
    return StubFrameProcessor(characters_dir, valid_character_ids)

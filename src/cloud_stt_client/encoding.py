import ctypes
import ctypes.util
import os
import platform
from pathlib import Path
import sys

from cloud_stt_client.config import AudioConfig


_OPUS_HANDLE = None
_PATCHED_FIND_LIBRARY = False


def setup_opus(explicit_path: str | None = None) -> None:
    global _OPUS_HANDLE
    if getattr(setup_opus, "_loaded", False):
        return

    errors: list[str] = []
    for candidate in _candidate_paths(explicit_path):
        try:
            if platform.system().lower().startswith("win"):
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(str(candidate.parent))
                os.environ["PATH"] = str(candidate.parent) + os.pathsep + os.environ.get(
                    "PATH", ""
                )
            _patch_find_library("opus", str(candidate))
            _OPUS_HANDLE = ctypes.CDLL(str(candidate))
            setup_opus._loaded = True
            return
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")

    system_path = ctypes.util.find_library("opus")
    if system_path:
        try:
            _OPUS_HANDLE = ctypes.CDLL(system_path)
            setup_opus._loaded = True
            return
        except OSError as exc:
            errors.append(f"{system_path}: {exc}")

    detail = "; ".join(errors) if errors else "no libopus candidate found"
    raise RuntimeError(f"Opus support requires libopus. Detail: {detail}")


def _candidate_paths(explicit_path: str | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    env_path = os.getenv("CLOUD_STT_OPUS_LIB")
    if env_path:
        candidates.append(Path(env_path))

    root = Path(__file__).resolve().parents[2]
    relative = _relative_opus_path()
    candidates.append(root / relative)
    candidates.extend(_python_env_opus_paths())
    return [path for path in candidates if path.exists()]


def _python_env_opus_paths() -> list[Path]:
    prefixes = []
    conda_prefix = os.getenv("CONDA_PREFIX")
    if conda_prefix:
        prefixes.append(Path(conda_prefix))
    prefixes.append(Path(sys.prefix))

    paths: list[Path] = []
    for prefix in dict.fromkeys(prefixes):
        if platform.system().lower().startswith("win"):
            paths.append(prefix / "Library/bin/opus.dll")
        elif platform.system().lower() == "darwin":
            paths.append(prefix / "lib/libopus.dylib")
        else:
            paths.append(prefix / "lib/libopus.so")
    return paths


def _relative_opus_path() -> Path:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "arm64" if "arm" in machine or "aarch64" in machine else "x64"
    if system.startswith("win"):
        return Path("libs/libopus/win/x64/opus.dll")
    if system == "darwin":
        return Path(f"libs/libopus/mac/{arch}/libopus.dylib")
    return Path(f"libs/libopus/linux/{arch}/libopus.so")


def _patch_find_library(name: str, path: str) -> None:
    global _PATCHED_FIND_LIBRARY
    if _PATCHED_FIND_LIBRARY:
        return
    original = ctypes.util.find_library

    def patched(value: str) -> str | None:
        if value == name:
            return path
        return original(value)

    ctypes.util.find_library = patched
    _PATCHED_FIND_LIBRARY = True


class AudioEncoder:
    def encode(self, pcm: bytes) -> bytes:
        raise NotImplementedError


class PcmPassthroughEncoder(AudioEncoder):
    def encode(self, pcm: bytes) -> bytes:
        return pcm


class OpusEncoder(AudioEncoder):
    def __init__(self, config: AudioConfig, opus_lib_path: str | None = None):
        setup_opus(opus_lib_path)
        try:
            import opuslib
        except ImportError as exc:
            raise RuntimeError("Opus support requires opuslib.") from exc
        self.frame_size = config.frame_samples
        self._opuslib = opuslib
        self._encoder = opuslib.Encoder(
            config.sample_rate,
            config.channels,
            opuslib.APPLICATION_VOIP,
        )

    def encode(self, pcm: bytes) -> bytes:
        try:
            return self._encoder.encode(pcm, self.frame_size)
        except self._opuslib.OpusError as exc:
            raise ValueError(f"opus encode failed: {exc}") from exc


def create_encoder(config: AudioConfig, opus_lib_path: str | None = None) -> AudioEncoder:
    if config.format == "pcm_s16le":
        return PcmPassthroughEncoder()
    if config.format == "opus":
        return OpusEncoder(config, opus_lib_path=opus_lib_path)
    raise ValueError(f"unsupported audio format: {config.format}")

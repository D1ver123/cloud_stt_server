from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from cloud_stt_server.audio.pcm import validate_pcm_s16le
from cloud_stt_server.config import FsmnVadConfig


@dataclass(frozen=True)
class FsmnVadState:
    speech_start: bool
    speech_end: bool = False
    start_time_ms: int | None = None
    end_time_ms: int | None = None


ModelFactory = Callable[[FsmnVadConfig], object]


class FsmnVadTracker:
    """Streaming FSMN-VAD tracker backed by FunASR."""

    def __init__(
        self,
        config: FsmnVadConfig,
        model_factory: ModelFactory | None = None,
    ):
        self.config = config
        self._model_factory = model_factory or _create_funasr_model
        self._model = None
        self._cache: dict = {}
        self._in_speech = False

    def observe(self, pcm: bytes) -> FsmnVadState:
        validate_pcm_s16le(pcm)
        if not pcm:
            return FsmnVadState(speech_start=self._in_speech)

        segments = self._detect_segments(pcm, is_final=False)
        started = False
        ended = False
        start_time_ms = None
        end_time_ms = None
        should_stream = self._in_speech

        for start_ms, end_ms in segments:
            if start_ms >= 0:
                started = True
                start_time_ms = start_ms
                self._in_speech = True
                should_stream = True
            if end_ms >= 0:
                ended = True
                end_time_ms = end_ms
                should_stream = should_stream or self._in_speech or started
                self._in_speech = False

        return FsmnVadState(
            speech_start=should_stream,
            speech_end=ended,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )

    def reset(self) -> None:
        self._cache = {}
        self._in_speech = False

    def _detect_segments(self, pcm: bytes, is_final: bool) -> list[tuple[int, int]]:
        model = self._load_model()
        audio = _pcm_s16le_to_float32(pcm)
        try:
            result = model.generate(
                input=audio,
                cache=self._cache,
                is_final=is_final,
                chunk_size=self.config.chunk_size_ms,
                max_end_silence_time=self.config.max_end_silence_time_ms,
                data_type="sound",
                fs=self.config.sample_rate,
            )
        except Exception as exc:
            raise RuntimeError(f"FSMN-VAD failed: {exc}") from exc
        return _extract_segments(result)

    def _load_model(self):
        if self._model is None:
            try:
                self._model = self._model_factory(self.config)
            except Exception as exc:
                raise RuntimeError(f"FSMN-VAD model load failed: {exc}") from exc
        return self._model


def _create_funasr_model(config: FsmnVadConfig):
    try:
        from funasr import AutoModel
    except ImportError as exc:
        raise RuntimeError("FunASR is required. Install with: pip install funasr") from exc

    return AutoModel(
        model=config.model,
        device=config.device,
        ncpu=config.ncpu,
        disable_update=True,
        disable_pbar=True,
        log_level="ERROR",
    )


def _pcm_s16le_to_float32(pcm: bytes) -> np.ndarray:
    samples = np.frombuffer(pcm, dtype="<i2")
    return samples.astype(np.float32) / 32768.0


def _extract_segments(result) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    if not isinstance(result, list):
        return segments
    for item in result:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, list):
            continue
        for segment in value:
            if not isinstance(segment, (list, tuple)) or len(segment) < 2:
                continue
            try:
                start_ms = int(segment[0])
                end_ms = int(segment[1])
            except (TypeError, ValueError):
                continue
            segments.append((start_ms, end_ms))
    return segments

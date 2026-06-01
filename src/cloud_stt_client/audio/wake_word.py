from dataclasses import dataclass
from pathlib import Path
import time

import numpy as np

from cloud_stt_client.config import WakeWordConfig


@dataclass(frozen=True)
class WakeWordDetection:
    text: str


class WakeWordDetector:
    """Sherpa-ONNX keyword spotter for local microphone wake-word gating."""

    def __init__(self, config: WakeWordConfig, sample_rate: int):
        self.config = config
        self.sample_rate = sample_rate
        self.model_dir = _resolve_model_dir(config.model_dir)
        self._spotter = self._create_spotter()
        self._stream = self._spotter.create_stream()
        self._last_detection_at = 0.0

    def process_pcm(self, pcm: bytes) -> WakeWordDetection | None:
        if not pcm:
            return None
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        self._stream.accept_waveform(sample_rate=self.sample_rate, waveform=samples)

        result = None
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
            result = self._spotter.get_result(self._stream)
            if result:
                break

        if not result:
            return None

        self._spotter.reset_stream(self._stream)
        now = time.monotonic()
        if now - self._last_detection_at < self.config.detection_cooldown_seconds:
            return None
        self._last_detection_at = now
        return WakeWordDetection(text=str(result))

    def reset(self) -> None:
        self._spotter.reset_stream(self._stream)

    def _create_spotter(self):
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                "sherpa-onnx is required for wake-word detection. "
                "Install with: pip install sherpa-onnx"
            ) from exc

        encoder = self.model_dir / "encoder.onnx"
        decoder = self.model_dir / "decoder.onnx"
        joiner = self.model_dir / "joiner.onnx"
        tokens = self.model_dir / "tokens.txt"
        keywords = self.model_dir / "keywords.txt"
        missing = [
            path
            for path in (encoder, decoder, joiner, tokens, keywords)
            if not path.exists()
        ]
        if missing:
            names = ", ".join(str(path) for path in missing)
            raise RuntimeError(f"wake-word model files are missing: {names}")

        return sherpa_onnx.KeywordSpotter(
            tokens=str(tokens),
            encoder=str(encoder),
            decoder=str(decoder),
            joiner=str(joiner),
            keywords_file=str(keywords),
            num_threads=self.config.num_threads,
            sample_rate=self.sample_rate,
            feature_dim=80,
            max_active_paths=self.config.max_active_paths,
            keywords_score=self.config.keywords_score,
            keywords_threshold=self.config.keywords_threshold,
            num_trailing_blanks=self.config.num_trailing_blanks,
            provider=self.config.provider,
        )


def _resolve_model_dir(model_dir: str) -> Path:
    path = Path(model_dir).expanduser()
    if path.is_absolute():
        return path
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path
    project_path = Path(__file__).resolve().parents[3] / path
    if project_path.exists():
        return project_path
    return cwd_path

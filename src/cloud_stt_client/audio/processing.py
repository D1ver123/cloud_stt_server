from collections import deque

import numpy as np

from cloud_stt_client.config import AudioConfig


def downmix_to_mono(samples: np.ndarray) -> np.ndarray:
    data = np.asarray(samples)
    if data.ndim == 1:
        return data.astype(np.float32, copy=False)
    if data.shape[1] == 1:
        return data[:, 0].astype(np.float32, copy=False)
    return data.astype(np.float32).mean(axis=1)


def resample_linear(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return samples.astype(np.float32, copy=False)
    if samples.size == 0:
        return samples.astype(np.float32, copy=False)

    duration = samples.size / float(source_rate)
    target_count = max(1, int(round(duration * target_rate)))
    source_x = np.linspace(0.0, duration, num=samples.size, endpoint=False)
    target_x = np.linspace(0.0, duration, num=target_count, endpoint=False)
    return np.interp(target_x, source_x, samples).astype(np.float32)


def float32_to_pcm16(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = np.rint(clipped * 32767.0).astype("<i2")
    return pcm.tobytes()


class AudioFrameConverter:
    """Convert device-native float32 chunks to protocol-sized PCM16 frames."""

    def __init__(self, config: AudioConfig):
        self.config = config
        self.source_sample_rate = config.source_sample_rate or config.sample_rate
        self._pending: deque[float] = deque()

    def convert(self, device_chunk: np.ndarray) -> list[bytes]:
        mono = downmix_to_mono(device_chunk)
        resampled = resample_linear(
            mono,
            source_rate=self.source_sample_rate,
            target_rate=self.config.sample_rate,
        )
        self._pending.extend(float(value) for value in resampled)

        frames: list[bytes] = []
        while len(self._pending) >= self.config.frame_samples:
            frame = np.fromiter(
                (self._pending.popleft() for _ in range(self.config.frame_samples)),
                dtype=np.float32,
                count=self.config.frame_samples,
            )
            frames.append(float32_to_pcm16(frame))
        return frames

    def flush(self) -> bytes | None:
        if not self._pending:
            return None
        values = list(self._pending)
        self._pending.clear()
        if len(values) < self.config.frame_samples:
            values.extend([0.0] * (self.config.frame_samples - len(values)))
        frame = np.asarray(values[: self.config.frame_samples], dtype=np.float32)
        return float32_to_pcm16(frame)


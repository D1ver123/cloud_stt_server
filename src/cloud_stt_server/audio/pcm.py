import math

import numpy as np


SAMPLE_WIDTH_BYTES = 2


def validate_pcm_s16le(data: bytes) -> None:
    if len(data) % SAMPLE_WIDTH_BYTES != 0:
        raise ValueError("pcm_s16le audio frames must contain whole samples")


def frame_byte_count(sample_rate: int, channels: int, frame_duration_ms: int) -> int:
    return sample_rate * channels * SAMPLE_WIDTH_BYTES * frame_duration_ms // 1000


def duration_ms(pcm: bytes, sample_rate: int, channels: int) -> float:
    if channels <= 0:
        raise ValueError("channels must be positive")
    return len(pcm) / SAMPLE_WIDTH_BYTES / channels / sample_rate * 1000


def rms_s16le(pcm: bytes) -> float:
    validate_pcm_s16le(pcm)
    samples = np.frombuffer(pcm, dtype="<i2")
    if samples.size == 0:
        return 0.0
    values = samples.astype(np.float32)
    return float(math.sqrt(float(np.mean(values * values))))


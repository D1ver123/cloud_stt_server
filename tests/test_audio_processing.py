import numpy as np

from cloud_stt_client.audio.processing import (
    AudioFrameConverter,
    downmix_to_mono,
    float32_to_pcm16,
    resample_linear,
)
from cloud_stt_client.config import AudioConfig


def test_downmix_to_mono_averages_channels():
    stereo = np.asarray([[1.0, -1.0], [0.5, 0.25]], dtype=np.float32)
    mono = downmix_to_mono(stereo)

    assert mono.shape == (2,)
    assert np.allclose(mono, [0.0, 0.375])


def test_resample_linear_changes_sample_count():
    source = np.ones(480, dtype=np.float32)
    target = resample_linear(source, source_rate=48000, target_rate=16000)

    assert len(target) == 160


def test_float32_to_pcm16_returns_little_endian_bytes():
    pcm = float32_to_pcm16(np.asarray([-1.0, 0.0, 1.0], dtype=np.float32))

    assert len(pcm) == 6
    assert np.frombuffer(pcm, dtype="<i2").tolist() == [-32767, 0, 32767]


def test_frame_converter_emits_protocol_frames():
    config = AudioConfig(sample_rate=16000, frame_duration_ms=20, source_sample_rate=48000)
    converter = AudioFrameConverter(config)
    source = np.ones((960, 2), dtype=np.float32) * 0.1

    frames = converter.convert(source)

    assert len(frames) == 1
    assert len(frames[0]) == config.frame_bytes


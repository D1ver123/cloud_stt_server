import wave

import numpy as np

from cloud_stt_client.audio.wav_source import read_pcm_s16le_wav
from cloud_stt_client.config import AudioConfig


def test_read_pcm_s16le_wav(tmp_path):
    path = tmp_path / "sample.wav"
    samples = np.zeros(320, dtype="<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(samples.tobytes())

    pcm = read_pcm_s16le_wav(path, AudioConfig())

    assert pcm == samples.tobytes()

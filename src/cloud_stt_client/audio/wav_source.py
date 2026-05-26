from collections.abc import AsyncIterator
from pathlib import Path
import wave

from cloud_stt_client.config import AudioConfig


def read_pcm_s16le_wav(path: Path, config: AudioConfig) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != config.channels:
            raise ValueError(f"wav must be mono, got {wav.getnchannels()} channels")
        if wav.getsampwidth() != 2:
            raise ValueError("wav must be 16-bit PCM")
        if wav.getframerate() != config.sample_rate:
            raise ValueError(
                f"wav sample rate must be {config.sample_rate} Hz, "
                f"got {wav.getframerate()} Hz"
            )
        if wav.getcomptype() != "NONE":
            raise ValueError("wav must be uncompressed PCM")
        return wav.readframes(wav.getnframes())


async def iter_wav_frames(path: Path, config: AudioConfig) -> AsyncIterator[bytes]:
    pcm = read_pcm_s16le_wav(path, config)
    frame_bytes = config.frame_bytes
    for offset in range(0, len(pcm), frame_bytes):
        frame = pcm[offset : offset + frame_bytes]
        if len(frame) < frame_bytes:
            frame += b"\x00" * (frame_bytes - len(frame))
        yield frame

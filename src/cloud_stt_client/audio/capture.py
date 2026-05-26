import asyncio
from collections.abc import AsyncIterator

import numpy as np

from cloud_stt_client.audio.devices import select_input_device
from cloud_stt_client.audio.processing import AudioFrameConverter
from cloud_stt_client.config import AudioConfig


class AudioCapture:
    """Microphone capture using device-native settings and protocol conversion."""

    def __init__(self, config: AudioConfig, queue_max_frames: int = 200):
        self.config = config
        self.queue_max_frames = queue_max_frames
        self.device = select_input_device(
            config.device_id,
            remember_explicit=config.device_id is not None,
        )
        self.source_sample_rate = config.source_sample_rate or self.device.sample_rate
        self.source_channels = min(config.source_channels or self.device.channels, 2)
        self.converter = AudioFrameConverter(
            AudioConfig(
                format=config.format,
                sample_rate=config.sample_rate,
                channels=config.channels,
                frame_duration_ms=config.frame_duration_ms,
                source_sample_rate=self.source_sample_rate,
                source_channels=self.source_channels,
                device_id=self.device.index,
            )
        )
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=queue_max_frames)
        self._stream = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def __aenter__(self) -> "AudioCapture":
        self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    def start(self) -> None:
        if self._stream is not None:
            return
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "sounddevice is required for microphone capture. "
                "Install with: pip install -e .[audio]"
            ) from exc

        self._loop = asyncio.get_running_loop()
        blocksize = int(self.source_sample_rate * self.config.frame_duration_ms / 1000)
        self._stream = sd.InputStream(
            device=self.device.index,
            samplerate=self.source_sample_rate,
            channels=self.source_channels,
            dtype=np.float32,
            blocksize=blocksize,
            callback=self._on_audio,
            latency="low",
        )
        self._stream.start()

    async def stop(self) -> None:
        if self._stream is None:
            return
        stream = self._stream
        self._stream = None
        try:
            stream.stop()
            stream.close()
        finally:
            tail = self.converter.flush()
            if tail is not None:
                await self._put_frame(tail)

    async def frames(self) -> AsyncIterator[bytes]:
        while self._stream is not None:
            yield await self._queue.get()

    def _on_audio(self, indata, frames, time_info, status) -> None:
        if self._loop is None:
            return
        try:
            for frame in self.converter.convert(indata.copy()):
                self._loop.call_soon_threadsafe(self._put_frame_nowait, frame)
        except Exception:
            return

    async def _put_frame(self, frame: bytes) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await self._queue.put(frame)

    def _put_frame_nowait(self, frame: bytes) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(frame)

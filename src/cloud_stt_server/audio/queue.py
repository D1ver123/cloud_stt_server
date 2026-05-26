import asyncio
from collections import deque

from cloud_stt_server.audio.pcm import duration_ms


class AudioChunkQueue:
    def __init__(self, max_seconds: int, sample_rate: int, channels: int):
        self.max_ms = max_seconds * 1000
        self.sample_rate = sample_rate
        self.channels = channels
        self._chunks: deque[bytes] = deque()
        self._duration_ms = 0.0

    def push(self, pcm: bytes) -> None:
        next_duration = self._duration_ms + duration_ms(
            pcm,
            self.sample_rate,
            self.channels,
        )
        if next_duration > self.max_ms:
            raise BufferError("audio chunk queue is full")
        self._chunks.append(pcm)
        self._duration_ms = next_duration

    def read_all(self) -> bytes:
        return b"".join(self._chunks)

    def clear(self) -> None:
        self._chunks.clear()
        self._duration_ms = 0.0


class AsyncAudioChunkQueue:
    def __init__(self, max_seconds: int, sample_rate: int, channels: int):
        self.max_ms = max_seconds * 1000
        self.sample_rate = sample_rate
        self.channels = channels
        self._queue: asyncio.Queue[tuple[bytes, float]] = asyncio.Queue()
        self._queued_duration_ms = 0.0
        self._lock = asyncio.Lock()

    async def push(self, pcm: bytes) -> None:
        chunk_duration = duration_ms(pcm, self.sample_rate, self.channels)
        async with self._lock:
            next_duration = self._queued_duration_ms + chunk_duration
            if next_duration > self.max_ms:
                raise BufferError("audio chunk queue is full")
            self._queued_duration_ms = next_duration
        self._queue.put_nowait((pcm, chunk_duration))

    async def get(self) -> bytes:
        pcm, chunk_duration = await self._queue.get()
        async with self._lock:
            self._queued_duration_ms -= chunk_duration
            if self._queued_duration_ms < 0:
                self._queued_duration_ms = 0.0
        return pcm

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

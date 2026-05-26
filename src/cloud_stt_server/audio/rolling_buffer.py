from collections import deque

from cloud_stt_server.audio.pcm import duration_ms


class RollingAudioBuffer:
    def __init__(self, max_ms: int, sample_rate: int, channels: int):
        self.max_ms = max_ms
        self.sample_rate = sample_rate
        self.channels = channels
        self._chunks: deque[bytes] = deque()
        self._duration_ms = 0.0

    def append(self, pcm: bytes) -> None:
        self._chunks.append(pcm)
        self._duration_ms += duration_ms(pcm, self.sample_rate, self.channels)
        self._trim()

    def read_all(self) -> bytes:
        return b"".join(self._chunks)

    def clear(self) -> None:
        self._chunks.clear()
        self._duration_ms = 0.0

    def _trim(self) -> None:
        while self._duration_ms > self.max_ms and self._chunks:
            removed = self._chunks.popleft()
            self._duration_ms -= duration_ms(
                removed,
                self.sample_rate,
                self.channels,
            )


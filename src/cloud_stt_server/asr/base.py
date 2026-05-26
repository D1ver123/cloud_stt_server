from abc import ABC, abstractmethod
from collections.abc import Callable


AsrEventCallback = Callable[[dict], None]


class RealtimeAsr(ABC):
    """Abstract interface for realtime ASR providers."""

    async def __aenter__(self) -> "RealtimeAsr":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    @abstractmethod
    async def start(self) -> None:
        """Open the provider-side realtime ASR stream."""

    @abstractmethod
    async def send_audio(self, data: bytes) -> None:
        """Send one PCM audio chunk to the provider."""

    @abstractmethod
    async def stop(self) -> str:
        """Stop the stream and return the latest final text if available."""

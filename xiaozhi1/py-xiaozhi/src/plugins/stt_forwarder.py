import asyncio
import inspect
from typing import Any, Awaitable, Callable

from src.plugins.base import Plugin
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

SttListener = Callable[[str, dict[str, Any]], Any | Awaitable[Any]]


class SttForwarderPlugin(Plugin):
    """Forward server STT text to in-process consumers.

    Other modules can use either callbacks or an asyncio.Queue:

        plugin = app.plugins.get_plugin("stt_forwarder")
        plugin.add_listener(callback)

        queue = plugin.subscribe_queue()
        item = await queue.get()
    """

    name = "stt_forwarder"
    priority = 55

    def __init__(self) -> None:
        super().__init__()
        self.app = None
        self.last_text: str | None = None
        self.last_message: dict[str, Any] | None = None
        self._listeners: list[SttListener] = []
        self._queues: set[asyncio.Queue] = set()

    async def setup(self, app: Any) -> None:
        self.app = app

    def add_listener(self, callback: SttListener) -> None:
        """Register a callback called as callback(text, raw_message)."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: SttListener) -> None:
        """Remove a previously registered callback."""
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def subscribe_queue(self, maxsize: int = 0) -> asyncio.Queue:
        """Create and register a queue that receives STT event dictionaries."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._queues.add(queue)
        return queue

    def unsubscribe_queue(self, queue: asyncio.Queue) -> None:
        """Unregister a queue returned by subscribe_queue()."""
        self._queues.discard(queue)

    def get_last_text(self) -> str | None:
        """Return the most recent STT text, if any."""
        return self.last_text

    def get_last_message(self) -> dict[str, Any] | None:
        """Return the most recent raw STT message, if any."""
        return self.last_message

    async def on_incoming_json(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        if message.get("type") != "stt":
            return

        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return

        text = text.strip()
        self.last_text = text
        self.last_message = dict(message)
        logger.info(f"语音转文字结果: {text}")

        event = {"text": text, "message": self.last_message}
        self._publish_to_queues(event)
        self._publish_to_listeners(text, self.last_message)

    def _publish_to_queues(self, event: dict[str, Any]) -> None:
        stale_queues = []
        for queue in list(self._queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("STT forward queue is full, dropping text")
            except Exception:
                stale_queues.append(queue)

        for queue in stale_queues:
            self._queues.discard(queue)

    def _publish_to_listeners(self, text: str, message: dict[str, Any]) -> None:
        for callback in list(self._listeners):
            try:
                result = callback(text, message)
                if inspect.isawaitable(result):
                    if self.app and hasattr(self.app, "spawn"):
                        self.app.spawn(result, "stt_forwarder:listener")
                    else:
                        asyncio.create_task(result)
            except Exception as e:
                logger.warning(f"STT forward listener failed: {e}")

    async def shutdown(self) -> None:
        self._listeners.clear()
        self._queues.clear()

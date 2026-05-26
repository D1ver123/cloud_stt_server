import asyncio
from collections.abc import AsyncIterator, Callable
import contextlib

from cloud_stt_client.audio.capture import AudioCapture
from cloud_stt_client.config import ClientConfig
from cloud_stt_client.encoding import create_encoder
from cloud_stt_client.protocol import RestSessionClient, SttWebSocketClient


EventHandler = Callable[[dict], None]


class VoiceSttClient:
    """End-to-end client pipeline: REST session, capture, encode, WebSocket stream."""

    def __init__(self, config: ClientConfig):
        self.config = config

    async def run(
        self,
        duration_seconds: float | None = None,
        on_event: EventHandler | None = None,
    ) -> None:
        session = await RestSessionClient(self.config.rest_base_url).create_session(
            self.config.audio,
            self.config.vad,
            self.config.asr,
            self.config.intent,
        )
        websocket_url = self.config.websocket_url or session.websocket_url
        encoder = create_encoder(self.config.audio)

        async with SttWebSocketClient(websocket_url) as ws:
            stop_event = asyncio.Event()
            event_task = asyncio.create_task(
                self._receive_events(ws, on_event, stop_event)
            )
            try:
                async with AudioCapture(
                    self.config.audio,
                    queue_max_frames=self.config.queue_max_frames,
                ) as capture:
                    deadline = (
                        asyncio.get_running_loop().time() + duration_seconds
                        if duration_seconds
                        else None
                    )
                    async for pcm_frame in capture.frames():
                        if stop_event.is_set():
                            break
                        try:
                            await ws.send_audio(encoder.encode(pcm_frame))
                        except RuntimeError as exc:
                            self._emit_error(on_event, str(exc))
                            stop_event.set()
                            break
                        if deadline and asyncio.get_running_loop().time() >= deadline:
                            break
            finally:
                await self._finish(ws, event_task)

    async def run_frames(
        self,
        frames: AsyncIterator[bytes],
        on_event: EventHandler | None = None,
        realtime: bool = False,
    ) -> None:
        session = await RestSessionClient(self.config.rest_base_url).create_session(
            self.config.audio,
            self.config.vad,
            self.config.asr,
            self.config.intent,
        )
        websocket_url = self.config.websocket_url or session.websocket_url
        encoder = create_encoder(self.config.audio)

        async with SttWebSocketClient(websocket_url) as ws:
            stop_event = asyncio.Event()
            event_task = asyncio.create_task(
                self._receive_events(ws, on_event, stop_event)
            )
            try:
                async for pcm_frame in frames:
                    if stop_event.is_set():
                        break
                    try:
                        await ws.send_audio(encoder.encode(pcm_frame))
                    except RuntimeError as exc:
                        self._emit_error(on_event, str(exc))
                        stop_event.set()
                        break
                    if realtime:
                        await asyncio.sleep(self.config.audio.frame_duration_ms / 1000)
            finally:
                await self._finish(ws, event_task)

    async def _receive_events(
        self,
        ws: SttWebSocketClient,
        on_event: EventHandler | None,
        stop_event: asyncio.Event,
    ) -> None:
        async for event in ws.events():
            if on_event is not None:
                on_event(event)
            if event.get("type") in {"stt.final", "error"}:
                stop_event.set()
                return

    def _emit_error(
        self,
        on_event: EventHandler | None,
        message: str,
    ) -> None:
        if on_event is not None:
            on_event({"type": "error", "message": message})

    async def _finish(
        self,
        ws: SttWebSocketClient,
        event_task: asyncio.Task,
    ) -> None:
        if self.config.send_commit_on_stop:
            with contextlib.suppress(Exception):
                await ws.commit()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(event_task, timeout=10.0)
        if not event_task.done():
            event_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await event_task

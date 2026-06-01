import asyncio
from collections.abc import AsyncIterator, Callable
import contextlib
import time

from cloud_stt_client.audio.capture import AudioCapture
from cloud_stt_client.audio.wake_word import WakeWordDetector
from cloud_stt_client.config import ClientConfig
from cloud_stt_client.encoding import create_encoder
from cloud_stt_client.protocol import (
    RestSessionClient,
    SttWebSocketClient,
    websocket_url_with_session,
)


EventHandler = Callable[[dict], None]
TimingHandler = Callable[[dict], None]
FinalEventHandler = Callable[[dict], None]
ActivityHandler = Callable[[], None]


class VoiceSttClient:
    """End-to-end client pipeline: REST session, capture, encode, WebSocket stream."""

    def __init__(self, config: ClientConfig):
        self.config = config

    async def run(
        self,
        duration_seconds: float | None = None,
        on_event: EventHandler | None = None,
        on_timing: TimingHandler | None = None,
        stop_on_final: bool = False,
    ) -> None:
        if self.config.wake_word.enabled:
            await self._run_with_wake_word(duration_seconds, on_event, on_timing)
            return

        started_at = time.perf_counter()
        self._emit_timing(on_timing, "start", started_at)
        session = await RestSessionClient(self.config.rest_base_url).create_session(
            self.config.audio,
            self.config.vad,
            self.config.asr,
            self.config.intent,
        )
        self._emit_timing(on_timing, "session_created", started_at)
        websocket_url = self._websocket_url_for_session(session)
        encoder = create_encoder(self.config.audio)
        self._emit_timing(on_timing, "encoder_ready", started_at)

        async with SttWebSocketClient(websocket_url) as ws:
            self._emit_timing(on_timing, "websocket_connected", started_at)
            stop_event = asyncio.Event()
            final_event = asyncio.Event()
            timing_state: dict[str, bool] = {}
            event_task = asyncio.create_task(
                self._receive_events(
                    ws,
                    on_event,
                    stop_event,
                    on_timing,
                    started_at,
                    timing_state,
                    stop_on_final=stop_on_final,
                    on_final=lambda event: final_event.set(),
                )
            )
            try:
                async with AudioCapture(
                    self.config.audio,
                    queue_max_frames=self.config.queue_max_frames,
                ) as capture:
                    self._emit_timing(on_timing, "capture_started", started_at)
                    wake_detector = self._create_wake_word_detector(on_event)
                    awake = wake_detector is None
                    deadline = (
                        asyncio.get_running_loop().time() + duration_seconds
                        if duration_seconds
                        else None
                    )
                    first_audio_sent = False
                    async for pcm_frame in capture.frames():
                        if stop_event.is_set():
                            break
                        if final_event.is_set() and wake_detector is not None:
                            final_event.clear()
                            awake = False
                            wake_detector.reset()
                            self._emit_timing(on_timing, "wake_word_waiting", started_at)
                        if not awake and wake_detector is not None:
                            detection = wake_detector.process_pcm(pcm_frame)
                            if detection is None:
                                if (
                                    deadline
                                    and asyncio.get_running_loop().time() >= deadline
                                ):
                                    break
                                continue
                            awake = True
                            final_event.clear()
                            self._emit_wake_word_detected(on_event, detection.text)
                            self._emit_timing(on_timing, "wake_word_detected", started_at)
                        try:
                            await ws.send_audio(encoder.encode(pcm_frame))
                            if not first_audio_sent:
                                first_audio_sent = True
                                self._emit_timing(on_timing, "first_audio_sent", started_at)
                        except RuntimeError as exc:
                            self._emit_error(on_event, str(exc))
                            stop_event.set()
                            break
                        if deadline and asyncio.get_running_loop().time() >= deadline:
                            break
            finally:
                await self._finish(ws, event_task, on_timing, started_at)

    async def _run_with_wake_word(
        self,
        duration_seconds: float | None,
        on_event: EventHandler | None,
        on_timing: TimingHandler | None,
    ) -> None:
        started_at = time.perf_counter()
        self._emit_timing(on_timing, "start", started_at)
        encoder = None
        stop_event: asyncio.Event | None = None
        final_event: asyncio.Event | None = None
        event_task: asyncio.Task | None = None
        ws: SttWebSocketClient | None = None
        first_audio_sent = False
        idle_deadline: float | None = None

        def refresh_idle_deadline() -> None:
            nonlocal idle_deadline
            idle_deadline = (
                asyncio.get_running_loop().time()
                + self._wake_word_idle_timeout_seconds()
            )

        async with AudioCapture(
            self.config.audio,
            queue_max_frames=self.config.queue_max_frames,
        ) as capture:
            self._emit_timing(on_timing, "capture_started", started_at)
            wake_detector = self._create_wake_word_detector(on_event)
            if wake_detector is None:
                raise RuntimeError("wake-word detector is not configured")
            self._emit_timing(on_timing, "wake_word_waiting", started_at)
            deadline = (
                asyncio.get_running_loop().time() + duration_seconds
                if duration_seconds
                else None
            )

            async for pcm_frame in capture.frames():
                if deadline and asyncio.get_running_loop().time() >= deadline:
                    break

                if ws is None:
                    detection = wake_detector.process_pcm(pcm_frame)
                    if detection is None:
                        continue
                    if self._is_interrupt_detection(detection.text):
                        wake_detector.reset()
                        self._emit_timing(on_timing, "wake_word_waiting", started_at)
                        continue
                    self._emit_wake_word_detected(on_event, detection.text)
                    self._emit_timing(on_timing, "wake_word_detected", started_at)
                    try:
                        try:
                            encoder = create_encoder(self.config.audio)
                        except Exception as exc:
                            raise RuntimeError(
                                f"encoder init after wake failed: {exc}"
                            ) from exc
                        self._emit_timing(on_timing, "encoder_ready", started_at)
                        ws, event_task, stop_event, final_event = (
                            await self._open_stream_after_wake(
                                on_event,
                                on_timing,
                                started_at,
                                on_activity=refresh_idle_deadline,
                            )
                        )
                    except Exception as exc:
                        self._emit_error(on_event, str(exc))
                        wake_detector.reset()
                        self._emit_timing(on_timing, "wake_word_waiting", started_at)
                        continue
                    first_audio_sent = False
                    refresh_idle_deadline()

                assert ws is not None
                assert stop_event is not None
                assert final_event is not None
                assert event_task is not None
                assert encoder is not None

                if (
                    idle_deadline is not None
                    and asyncio.get_running_loop().time() >= idle_deadline
                ):
                    self._emit_timing(on_timing, "wake_word_idle_timeout", started_at)
                    await self._close_open_stream(
                        ws,
                        event_task,
                        on_timing,
                        started_at,
                    )
                    ws = None
                    encoder = None
                    event_task = None
                    stop_event = None
                    final_event = None
                    idle_deadline = None
                    wake_detector.reset()
                    self._emit_timing(on_timing, "wake_word_waiting", started_at)
                    continue

                if stop_event.is_set():
                    await self._close_open_stream(
                        ws,
                        event_task,
                        on_timing,
                        started_at,
                    )
                    ws = None
                    encoder = None
                    event_task = None
                    stop_event = None
                    final_event = None
                    idle_deadline = None
                    wake_detector.reset()
                    self._emit_timing(on_timing, "wake_word_waiting", started_at)
                    continue

                detection = wake_detector.process_pcm(pcm_frame)
                if detection is not None and self._is_interrupt_detection(detection.text):
                    self._emit_wake_word_interrupt(on_event, detection.text)
                    self._emit_timing(on_timing, "wake_word_interrupted", started_at)
                    await self._close_open_stream(
                        ws,
                        event_task,
                        on_timing,
                        started_at,
                    )
                    ws = None
                    encoder = None
                    event_task = None
                    stop_event = None
                    final_event = None
                    idle_deadline = None
                    wake_detector.reset()
                    self._emit_timing(on_timing, "wake_word_waiting", started_at)
                    continue

                try:
                    await ws.send_audio(encoder.encode(pcm_frame))
                    if not first_audio_sent:
                        first_audio_sent = True
                        self._emit_timing(on_timing, "first_audio_sent", started_at)
                except RuntimeError as exc:
                    self._emit_error(on_event, str(exc))
                    await self._close_open_stream(
                        ws,
                        event_task,
                        on_timing,
                        started_at,
                    )
                    ws = None
                    encoder = None
                    event_task = None
                    stop_event = None
                    final_event = None
                    idle_deadline = None
                    wake_detector.reset()
                    self._emit_timing(on_timing, "wake_word_waiting", started_at)

        if ws is not None and event_task is not None:
            await self._close_open_stream(ws, event_task, on_timing, started_at)
        self._emit_timing(on_timing, "finished", started_at)

    async def _open_stream_after_wake(
        self,
        on_event: EventHandler | None,
        on_timing: TimingHandler | None,
        started_at: float,
        on_activity: ActivityHandler | None = None,
    ) -> tuple[SttWebSocketClient, asyncio.Task, asyncio.Event, asyncio.Event]:
        try:
            session = await RestSessionClient(self.config.rest_base_url).create_session(
                self.config.audio,
                self.config.vad,
                self.config.asr,
                self.config.intent,
            )
        except Exception as exc:
            raise RuntimeError(f"session creation after wake failed: {exc}") from exc
        self._emit_timing(on_timing, "session_created", started_at)
        websocket_url = self._websocket_url_for_session(session)
        ws = SttWebSocketClient(websocket_url)
        try:
            await ws.__aenter__()
        except Exception:
            with contextlib.suppress(Exception):
                await ws.__aexit__(None, None, None)
            raise RuntimeError(
                f"websocket connect after wake failed: {websocket_url}: {exc}"
            ) from exc
        self._emit_timing(on_timing, "websocket_connected", started_at)
        stop_event = asyncio.Event()
        final_event = asyncio.Event()
        timing_state: dict[str, bool] = {}
        event_task = asyncio.create_task(
            self._receive_events(
                ws,
                on_event,
                stop_event,
                on_timing,
                started_at,
                timing_state,
                stop_on_final=False,
                on_final=lambda event: final_event.set(),
                on_activity=on_activity,
            )
        )
        return ws, event_task, stop_event, final_event

    async def _close_open_stream(
        self,
        ws: SttWebSocketClient,
        event_task: asyncio.Task,
        on_timing: TimingHandler | None,
        started_at: float,
    ) -> None:
        try:
            await self._finish(
                ws,
                event_task,
                on_timing,
                started_at,
                emit_finished=False,
            )
        finally:
            await ws.__aexit__(None, None, None)

    async def run_frames(
        self,
        frames: AsyncIterator[bytes],
        on_event: EventHandler | None = None,
        realtime: bool = False,
        on_timing: TimingHandler | None = None,
        stop_on_final: bool = True,
    ) -> None:
        started_at = time.perf_counter()
        self._emit_timing(on_timing, "start", started_at)
        session = await RestSessionClient(self.config.rest_base_url).create_session(
            self.config.audio,
            self.config.vad,
            self.config.asr,
            self.config.intent,
        )
        self._emit_timing(on_timing, "session_created", started_at)
        websocket_url = self._websocket_url_for_session(session)
        encoder = create_encoder(self.config.audio)
        self._emit_timing(on_timing, "encoder_ready", started_at)

        async with SttWebSocketClient(websocket_url) as ws:
            self._emit_timing(on_timing, "websocket_connected", started_at)
            stop_event = asyncio.Event()
            timing_state: dict[str, bool] = {}
            event_task = asyncio.create_task(
                self._receive_events(
                    ws,
                    on_event,
                    stop_event,
                    on_timing,
                    started_at,
                    timing_state,
                    stop_on_final=stop_on_final,
                    on_final=None,
                )
            )
            try:
                first_audio_sent = False
                async for pcm_frame in frames:
                    if stop_event.is_set():
                        break
                    try:
                        await ws.send_audio(encoder.encode(pcm_frame))
                        if not first_audio_sent:
                            first_audio_sent = True
                            self._emit_timing(on_timing, "first_audio_sent", started_at)
                    except RuntimeError as exc:
                        self._emit_error(on_event, str(exc))
                        stop_event.set()
                        break
                    if realtime:
                        await asyncio.sleep(self.config.audio.frame_duration_ms / 1000)
            finally:
                await self._finish(ws, event_task, on_timing, started_at)

    async def _receive_events(
        self,
        ws: SttWebSocketClient,
        on_event: EventHandler | None,
        stop_event: asyncio.Event,
        on_timing: TimingHandler | None,
        started_at: float,
        timing_state: dict[str, bool],
        stop_on_final: bool,
        on_final: FinalEventHandler | None,
        on_activity: ActivityHandler | None = None,
    ) -> None:
        async for event in ws.events():
            if not timing_state.get("first_server_event"):
                timing_state["first_server_event"] = True
                self._emit_timing(on_timing, "first_server_event", started_at)
            if (
                event.get("type") in {"stt.partial", "stt.final"}
                and not timing_state.get("first_stt_result")
            ):
                timing_state["first_stt_result"] = True
                self._emit_timing(on_timing, "first_stt_result", started_at)
            if event.get("type") in {"stt.partial", "stt.final"} and on_activity is not None:
                on_activity()
            if on_event is not None:
                on_event(event)
            if event.get("type") == "stt.final" and on_final is not None:
                on_final(event)
            if event.get("type") == "error" or (
                stop_on_final and event.get("type") == "stt.final"
            ):
                self._emit_timing(on_timing, "terminal_event", started_at)
                stop_event.set()
                return

    def _emit_error(
        self,
        on_event: EventHandler | None,
        message: str,
    ) -> None:
        if on_event is not None:
            on_event({"type": "error", "message": message})

    def _websocket_url_for_session(self, session) -> str:
        if self.config.websocket_url:
            return websocket_url_with_session(
                self.config.websocket_url,
                session.session_id,
            )
        return session.websocket_url

    def _emit_wake_word_detected(
        self,
        on_event: EventHandler | None,
        text: str,
    ) -> None:
        if on_event is not None:
            on_event({"type": "wake_word.detected", "text": text})

    def _emit_wake_word_interrupt(
        self,
        on_event: EventHandler | None,
        text: str,
    ) -> None:
        if on_event is not None:
            on_event({"type": "wake_word.interrupted", "text": text})

    def _is_interrupt_detection(self, text: str) -> bool:
        normalized = text.strip().casefold()
        return any(
            normalized == value.strip().casefold()
            for value in self.config.wake_word.interrupt_texts
        )

    def _wake_word_idle_timeout_seconds(self) -> float:
        return self.config.wake_word.idle_timeout_seconds

    def _create_wake_word_detector(
        self,
        on_event: EventHandler | None,
    ) -> WakeWordDetector | None:
        if not self.config.wake_word.enabled:
            return None
        try:
            return WakeWordDetector(
                self.config.wake_word,
                sample_rate=self.config.audio.sample_rate,
            )
        except RuntimeError as exc:
            self._emit_error(on_event, str(exc))
            raise

    async def _finish(
        self,
        ws: SttWebSocketClient,
        event_task: asyncio.Task,
        on_timing: TimingHandler | None,
        started_at: float,
        emit_finished: bool = True,
    ) -> None:
        if self.config.send_commit_on_stop:
            with contextlib.suppress(Exception):
                await ws.commit()
                self._emit_timing(on_timing, "commit_sent", started_at)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(event_task, timeout=10.0)
        if not event_task.done():
            event_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await event_task
        if emit_finished:
            self._emit_timing(on_timing, "finished", started_at)

    def _emit_timing(
        self,
        on_timing: TimingHandler | None,
        stage: str,
        started_at: float,
    ) -> None:
        if on_timing is None:
            return
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        on_timing(
            {
                "type": "client.timing",
                "stage": stage,
                "elapsed_ms": round(elapsed_ms, 2),
            }
        )

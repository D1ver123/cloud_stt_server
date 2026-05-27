import asyncio
import contextlib
from dataclasses import dataclass

from cloud_stt_server.adapter.text_adapter import normalize_asr_text
from cloud_stt_server.asr.base import AsrEventCallback, RealtimeAsr
from cloud_stt_server.config import DashScopeAsrConfig


@dataclass(frozen=True)
class DashScopeAudioParams:
    format: str = "pcm"
    sample_rate: int = 16000


class _RecognitionCallback:
    def __init__(self, owner: "DashScopeRealtimeAsr"):
        from dashscope.audio.asr import RecognitionCallback

        class Callback(RecognitionCallback):
            def on_open(callback_self) -> None:
                owner._dispatch({"type": "asr.start", "provider": "dashscope"})

            def on_complete(callback_self) -> None:
                owner._mark_completed()

            def on_error(callback_self, result) -> None:
                owner._dispatch({"type": "error", "message": str(result)})
                owner._mark_completed()

            def on_close(callback_self) -> None:
                owner._mark_completed()

            def on_event(callback_self, result) -> None:
                owner._handle_result(result)

        self.instance = Callback()


class DashScopeRealtimeAsr(RealtimeAsr):
    """Async wrapper around DashScope fun-asr-realtime."""

    def __init__(
        self,
        config: DashScopeAsrConfig,
        audio: DashScopeAudioParams,
        on_event: AsrEventCallback,
        hotword_id: str | None = None,
    ):
        config.validate()
        self.config = config
        self.audio = audio
        self.on_event = on_event
        self.hotword_id = hotword_id
        self._loop: asyncio.AbstractEventLoop | None = None
        self._recognition = None
        self._lock = asyncio.Lock()
        self._started = False
        self._completed = asyncio.Event()
        self._final_text = ""

    async def start(self) -> None:
        if self._started:
            return
        self._loop = asyncio.get_running_loop()
        try:
            import dashscope
            from dashscope.audio.asr import Recognition
        except ImportError as exc:
            raise RuntimeError(
                "DashScope SDK is required. Install with: pip install dashscope"
            ) from exc

        dashscope.api_key = self.config.api_key
        callback = _RecognitionCallback(self).instance
        self._completed = asyncio.Event()
        self._final_text = ""
        self._recognition = Recognition(
            model=self.config.model,
            callback=callback,
            format=self.audio.format,
            sample_rate=self.audio.sample_rate,
        )
        start_kwargs = {
            "disfluency_removal_enabled": self.config.disfluency_removal_enabled,
        }
        if self.hotword_id:
            start_kwargs["phrase_id"] = self.hotword_id
        await asyncio.to_thread(self._recognition.start, **start_kwargs)
        self._started = True

    async def send_audio(self, data: bytes) -> None:
        if not self._started or self._recognition is None:
            raise RuntimeError("DashScope ASR recognition is not started")
        async with self._lock:
            await asyncio.to_thread(self._recognition.send_audio_frame, data)

    async def stop(self) -> str:
        if self._recognition is None:
            return self._final_text
        try:
            if self._started:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self._recognition.stop)
            try:
                await asyncio.wait_for(self._completed.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                pass
        finally:
            self._started = False
            self._recognition = None
        return self._final_text

    def _dispatch(self, event: dict) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self.on_event, event)

    def _mark_completed(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._completed.set)

    def _handle_result(self, result) -> None:
        sentence = result.get_sentence()
        if isinstance(sentence, list):
            for item in sentence:
                self._handle_sentence(item)
        elif isinstance(sentence, dict):
            self._handle_sentence(sentence)

    def _handle_sentence(self, sentence: dict) -> None:
        text = normalize_asr_text(str(sentence.get("text", "")))
        if not text:
            return
        if sentence.get("end_time") is not None:
            self._final_text = text
            self._dispatch({"type": "stt.final", "text": text})
        else:
            self._dispatch({"type": "stt.partial", "text": text})

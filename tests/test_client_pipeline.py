import asyncio
from pathlib import Path
import time

from cloud_stt_client.config import ClientConfig, RecognitionLogConfig, WakeWordConfig
import cloud_stt_client.pipeline as pipeline
from cloud_stt_client.pipeline import VoiceSttClient
from cloud_stt_client.protocol import SttSession
from cloud_stt_client.recognition_log import ConversationRecognitionLog


class FakeEventSocket:
    def __init__(self, events):
        self._events = events

    async def events(self):
        for event in self._events:
            yield event


def test_receive_events_can_keep_running_after_final():
    async def run_scenario():
        client = VoiceSttClient(ClientConfig())
        stop_event = asyncio.Event()
        received = []

        await client._receive_events(
            FakeEventSocket([{"type": "stt.final", "text": "hello"}]),
            received.append,
            stop_event,
            None,
            time.perf_counter(),
            {},
            stop_on_final=False,
            on_final=None,
        )

        assert received == [{"type": "stt.final", "text": "hello"}]
        assert not stop_event.is_set()

    asyncio.run(run_scenario())


def test_receive_events_can_stop_on_final_for_single_utterance_mode():
    async def run_scenario():
        client = VoiceSttClient(ClientConfig())
        stop_event = asyncio.Event()

        await client._receive_events(
            FakeEventSocket([{"type": "stt.final", "text": "hello"}]),
            None,
            stop_event,
            None,
            time.perf_counter(),
            {},
            stop_on_final=True,
            on_final=None,
        )

        assert stop_event.is_set()

    asyncio.run(run_scenario())


def test_receive_events_reports_stt_activity():
    async def run_scenario():
        client = VoiceSttClient(ClientConfig())
        stop_event = asyncio.Event()
        activity_count = 0

        def on_activity():
            nonlocal activity_count
            activity_count += 1

        await client._receive_events(
            FakeEventSocket(
                [
                    {"type": "stt.partial", "text": "he"},
                    {"type": "stt.final", "text": "hello"},
                ]
            ),
            None,
            stop_event,
            None,
            time.perf_counter(),
            {},
            stop_on_final=False,
            on_final=None,
            on_activity=on_activity,
        )

        assert activity_count == 2

    asyncio.run(run_scenario())


def test_receive_events_records_final_results_for_client_log(tmp_path):
    async def run_scenario():
        client = VoiceSttClient(ClientConfig())
        stop_event = asyncio.Event()
        recognition_log = ConversationRecognitionLog(tmp_path, "stt_test")

        await client._receive_events(
            FakeEventSocket(
                [
                    {"type": "stt.partial", "text": "he"},
                    {"type": "stt.final", "text": "hello", "intent": {"ok": True}},
                ]
            ),
            None,
            stop_event,
            None,
            time.perf_counter(),
            {},
            stop_on_final=False,
            on_final=None,
            recognition_log=recognition_log,
        )

        path = recognition_log.write()

        assert path is not None
        assert path.exists()
        assert '"result_count": 1' in path.read_text(encoding="utf-8")
        assert '"text": "hello"' in path.read_text(encoding="utf-8")

    asyncio.run(run_scenario())


def test_finish_writes_recognition_log_and_emits_path(tmp_path):
    class FakeWebSocket:
        async def commit(self):
            pass

    async def run_scenario():
        client = VoiceSttClient(
            ClientConfig(
                recognition_log=RecognitionLogConfig(directory=str(tmp_path)),
            )
        )
        recognition_log = client._create_recognition_log("stt_test")
        recognition_log.record_final({"type": "stt.final", "text": "hello"})
        events = []
        event_task = asyncio.create_task(asyncio.sleep(0))

        await client._finish(
            FakeWebSocket(),
            event_task,
            None,
            time.perf_counter(),
            on_event=events.append,
            recognition_log=recognition_log,
        )

        log_events = [
            event for event in events if event.get("type") == "client.recognition_log"
        ]
        assert len(log_events) == 1
        assert log_events[0]["result_count"] == 1
        assert tmp_path.joinpath(Path(log_events[0]["path"]).name).exists()

    asyncio.run(run_scenario())


def test_wake_word_interrupt_texts_are_matched_exactly():
    client = VoiceSttClient(ClientConfig(wake_word=WakeWordConfig(enabled=True)))

    assert client._is_interrupt_detection("停下")
    assert client._is_interrupt_detection(" 退出 ")
    assert not client._is_interrupt_detection("你好小旭")


def test_wake_word_mode_does_not_connect_before_detection(monkeypatch):
    class FakeCapture:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def frames(self):
            yield b"\x00\x00" * 320
            yield b"\x00\x00" * 320

    class FakeWakeWordDetector:
        def __init__(self, *args, **kwargs):
            pass

        def process_pcm(self, pcm):
            return None

        def reset(self):
            pass

    async def fail_create_session(*args, **kwargs):
        raise AssertionError("session should not be created before wake-word detection")

    monkeypatch.setattr(pipeline, "AudioCapture", FakeCapture)
    monkeypatch.setattr(pipeline, "WakeWordDetector", FakeWakeWordDetector)
    monkeypatch.setattr(
        pipeline.RestSessionClient,
        "create_session",
        fail_create_session,
    )

    asyncio.run(
        VoiceSttClient(ClientConfig(wake_word=WakeWordConfig(enabled=True))).run()
    )


def test_websocket_override_gets_current_session_id():
    client = VoiceSttClient(
        ClientConfig(websocket_url="ws://public.example/stt/v1/stream?token=x")
    )
    session = SttSession(
        session_id="stt_123",
        websocket_url="ws://internal.example/stt/v1/stream?session_id=bad",
    )

    url = client._websocket_url_for_session(session)

    assert "token=x" in url
    assert "session_id=stt_123" in url

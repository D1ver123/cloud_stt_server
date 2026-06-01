import asyncio
import time

from cloud_stt_client.config import ClientConfig, WakeWordConfig
import cloud_stt_client.pipeline as pipeline
from cloud_stt_client.pipeline import VoiceSttClient
from cloud_stt_client.protocol import SttSession


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

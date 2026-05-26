import asyncio

from cloud_stt_client.config import (
    AsrConfig,
    AudioConfig,
    IntentConfig,
    UserSemanticsConfig,
    VadConfig,
)
from cloud_stt_client.protocol import RestSessionClient, SttSession
from cloud_stt_client.protocol import websocket_url_with_session


def test_websocket_url_with_session_adds_query_param():
    url = websocket_url_with_session("ws://127.0.0.1:8000/stt/v1/stream", "abc")

    assert url == "ws://127.0.0.1:8000/stt/v1/stream?session_id=abc"


def test_websocket_url_with_session_preserves_existing_query():
    url = websocket_url_with_session("ws://host/path?token=x", "abc")

    assert url in {
        "ws://host/path?token=x&session_id=abc",
        "ws://host/path?session_id=abc&token=x",
    }


def test_rest_session_payload_includes_optional_hotword_id(monkeypatch):
    captured = {}

    def fake_post_session(self, payload):
        captured["payload"] = payload
        return SttSession(session_id="stt_test", websocket_url="ws://test")

    monkeypatch.setattr(RestSessionClient, "_post_session", fake_post_session)

    asyncio.run(
        RestSessionClient("http://test").create_session(
            AudioConfig(format="opus"),
            VadConfig(),
            AsrConfig(provider="dashscope", hotword_id="phrase_123"),
        )
    )

    assert captured["payload"]["asr"] == {
        "provider": "dashscope",
        "hotword_id": "phrase_123",
    }


def test_rest_session_payload_includes_intent_parameters(monkeypatch):
    captured = {}

    def fake_post_session(self, payload):
        captured["payload"] = payload
        return SttSession(session_id="stt_test", websocket_url="ws://test")

    monkeypatch.setattr(RestSessionClient, "_post_session", fake_post_session)

    asyncio.run(
        RestSessionClient("http://test").create_session(
            AudioConfig(format="opus"),
            VadConfig(),
            AsrConfig(provider="dashscope"),
            IntentConfig(
                user_semantics=UserSemanticsConfig(
                    client_id="工匠汇",
                    enterprise_id="ent_1",
                    device_id="robot_1",
                ),
                current_time="星期二 2026-05-26 10:00:00",
                location="苏州",
            ),
        )
    )

    assert captured["payload"]["intent"] == {
        "enabled": True,
        "user_semantics": {
            "client_id": "工匠汇",
            "enterprise_id": "ent_1",
            "device_id": "robot_1",
        },
        "current_time": "星期二 2026-05-26 10:00:00",
        "location": "苏州",
    }

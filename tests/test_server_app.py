from fastapi.testclient import TestClient

from cloud_stt_server.app import _attach_intent_result, app
from cloud_stt_server.command.models import IntentParams, UserSemantics
from cloud_stt_server.protocol import AsrParams, AudioParams, VadParams
from cloud_stt_server.sessions import SttSession


def test_health_endpoint():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_session_returns_websocket_url():
    client = TestClient(app)

    response = client.post(
        "/stt/v1/sessions",
        json={
            "audio": {
                "format": "pcm_s16le",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration_ms": 20,
            },
            "vad": {"engine": "fsmn", "pre_roll_ms": 200},
            "asr": {"provider": "dashscope"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"].startswith("stt_")
    assert "/stt/v1/stream?session_id=" in payload["websocket_url"]


def test_session_status_includes_asr_provider():
    client = TestClient(app)
    created = client.post(
        "/stt/v1/sessions",
        json={
            "audio": {
                "format": "pcm_s16le",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration_ms": 20,
            },
            "vad": {"engine": "fsmn", "pre_roll_ms": 200},
            "asr": {"provider": "dashscope"},
        },
    )
    session_id = created.json()["session_id"]

    response = client.get(f"/stt/v1/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["asr"] == {"provider": "dashscope", "hotword_id": None}
    assert response.json()["intent"]["enabled"] is True
    assert response.json()["intent"]["user_semantics"]["client_id"] == "工匠汇"


def test_session_status_includes_hotword_id():
    client = TestClient(app)
    created = client.post(
        "/stt/v1/sessions",
        json={
            "audio": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration_ms": 20,
            },
            "vad": {"engine": "fsmn", "pre_roll_ms": 200},
            "asr": {"provider": "dashscope", "hotword_id": "phrase_123"},
        },
    )
    session_id = created.json()["session_id"]

    response = client.get(f"/stt/v1/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["asr"] == {
        "provider": "dashscope",
        "hotword_id": "phrase_123",
    }


def test_session_status_includes_intent_parameters():
    client = TestClient(app)
    created = client.post(
        "/stt/v1/sessions",
        json={
            "audio": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration_ms": 20,
            },
            "vad": {"engine": "fsmn", "pre_roll_ms": 200},
            "asr": {"provider": "dashscope"},
            "intent": {
                "enabled": True,
                "user_semantics": {
                    "client_id": "工匠汇",
                    "enterprise_id": "ent_1",
                    "device_id": "robot_1",
                },
                "current_time": "星期二 2026-05-26 10:00:00",
                "location": "苏州",
            },
        },
    )
    session_id = created.json()["session_id"]

    response = client.get(f"/stt/v1/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["intent"] == {
        "enabled": True,
        "user_semantics": {
            "client_id": "工匠汇",
            "enterprise_id": "ent_1",
            "device_id": "robot_1",
            "deviceid": None,
        },
        "current_time": "星期二 2026-05-26 10:00:00",
        "location": "苏州",
    }


def test_create_session_rejects_unknown_asr_provider():
    client = TestClient(app)

    response = client.post(
        "/stt/v1/sessions",
        json={
            "audio": {
                "format": "pcm_s16le",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration_ms": 20,
            },
            "vad": {"engine": "fsmn", "pre_roll_ms": 200},
            "asr": {"provider": "unknown"},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "unsupported asr provider"


def test_final_event_attaches_intent_response():
    session = SttSession(
        session_id="stt_123",
        audio=AudioParams(),
        vad=VadParams(),
        asr=AsrParams(),
        intent=IntentParams(
            user_semantics=UserSemantics(
                client_id="工匠汇",
                device_id="robot_1",
            )
        ),
        created_at=0,
        expires_at=9999999999,
    )

    event = _attach_intent_result({"type": "stt.final", "text": "请向前走"}, session)

    assert event["intent"]["status"] == 1
    assert event["intent"]["nlp"][0]["english_domain"] == "robot_control"
    assert event["intent"]["nlp"][0]["intent"] == "move_forward"
    assert event["intent"]["nlp"][0]["slots"] == {"matched_text": "向前"}

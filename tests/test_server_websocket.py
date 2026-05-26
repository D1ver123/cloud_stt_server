from fastapi.testclient import TestClient

import cloud_stt_server.app as server_app


def test_websocket_reports_audio_decoder_startup_error(monkeypatch):
    def fail_decoder(*args, **kwargs):
        raise RuntimeError("Opus support requires libopus")

    monkeypatch.setattr(server_app, "AudioDecoder", fail_decoder)
    client = TestClient(server_app.app)
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
        },
    )
    session_id = created.json()["session_id"]

    with client.websocket_connect(f"/stt/v1/stream?session_id={session_id}") as ws:
        event = ws.receive_json()

    assert event == {"type": "error", "message": "Opus support requires libopus"}

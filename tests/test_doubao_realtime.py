import gzip
import json

from cloud_stt_server.asr.doubao_realtime import (
    FULL_SERVER_RESPONSE,
    GZIP_COMPRESSION,
    JSON_SERIALIZATION,
    NEG_WITH_SEQUENCE,
    POS_SEQUENCE,
    DoubaoAudioParams,
    DoubaoRealtimeAsr,
    _build_header,
    _extract_text,
    parse_doubao_frame,
)
from cloud_stt_server.config import DoubaoAsrConfig


def _server_response(payload: dict, flags: int = POS_SEQUENCE) -> bytes:
    body = gzip.compress(json.dumps(payload).encode("utf-8"))
    frame = bytearray(
        _build_header(
            message_type=FULL_SERVER_RESPONSE,
            flags=flags,
            serialization=JSON_SERIALIZATION,
            compression=GZIP_COMPRESSION,
        )
    )
    frame.extend((1).to_bytes(4, "big", signed=True))
    frame.extend(len(body).to_bytes(4, "big"))
    frame.extend(body)
    return bytes(frame)


def test_parse_doubao_frame_decodes_gzip_json_response():
    frame = parse_doubao_frame(
        _server_response({"result": {"text": "向前", "utterances": []}})
    )

    assert frame.message_type == FULL_SERVER_RESPONSE
    assert frame.sequence == 1
    assert frame.payload == {"result": {"text": "向前", "utterances": []}}


def test_parse_doubao_frame_marks_negative_sequence_as_final():
    frame = parse_doubao_frame(
        _server_response({"result": {"text": "完成"}}, flags=NEG_WITH_SEQUENCE)
    )

    assert frame.is_final is True


def test_extract_text_uses_definite_utterances_as_final_result():
    text, is_final = _extract_text(
        {
            "result": {
                "text": "四川话识别中",
                "utterances": [
                    {"text": "四川话识别", "definite": True},
                    {"text": "中", "definite": False},
                ],
            }
        }
    )

    assert text == "四川话识别"
    assert is_final is True


def test_doubao_request_omits_language_for_default_chinese_dialect_model():
    asr = DoubaoRealtimeAsr(
        config=DoubaoAsrConfig(api_key="test_key"),
        audio=DoubaoAudioParams(),
        on_event=lambda event: None,
    )

    payload = asr._request_payload()

    assert "language" not in payload["audio"]
    assert payload["request"]["enable_nonstream"] is True
    assert payload["request"]["model_name"] == "bigmodel"


def test_doubao_handle_response_can_force_final_on_negative_frame():
    events = []
    asr = DoubaoRealtimeAsr(
        config=DoubaoAsrConfig(api_key="test_key"),
        audio=DoubaoAudioParams(),
        on_event=events.append,
    )

    asr._handle_response({"result": {"text": "最终结果"}}, force_final=True)

    assert events == [{"type": "stt.final", "text": "最终结果"}]

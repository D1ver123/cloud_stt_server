import asyncio
import contextlib

from cloud_stt_server.adapter.text_adapter import (
    build_intent_request,
    command_to_partner_response,
    normalize_asr_text,
)
from cloud_stt_server.app import _send_asr_audio_worker
from cloud_stt_server.audio.decoder import AudioDecoder
from cloud_stt_server.audio.queue import AsyncAudioChunkQueue, AudioChunkQueue
from cloud_stt_server.audio.rolling_buffer import RollingAudioBuffer
from cloud_stt_server.command.models import IntentParams, RobotCommand, UserSemantics


def test_pcm_decoder_passes_valid_pcm():
    decoder = AudioDecoder(
        audio_format="pcm_s16le",
        sample_rate=16000,
        channels=1,
        frame_duration_ms=20,
    )
    pcm = b"\x00\x00" * 320

    assert decoder.decode(pcm) == pcm


def test_rolling_buffer_keeps_recent_audio():
    buffer = RollingAudioBuffer(max_ms=20, sample_rate=16000, channels=1)
    frame = b"\x00\x00" * 320

    buffer.append(frame)
    buffer.append(frame)

    assert buffer.read_all() == frame


def test_audio_queue_rejects_overflow():
    queue = AudioChunkQueue(max_seconds=1, sample_rate=16000, channels=1)
    one_second = b"\x00\x00" * 16000
    queue.push(one_second)

    try:
        queue.push(b"\x00\x00" * 320)
    except BufferError as exc:
        assert "full" in str(exc)
    else:
        raise AssertionError("expected BufferError")


def test_async_audio_queue_rejects_overflow_while_asr_send_blocks():
    class BlockingAsr:
        def __init__(self):
            self.started = asyncio.Event()

        async def send_audio(self, data):
            self.started.set()
            await asyncio.Event().wait()

    async def run_scenario():
        queue = AsyncAudioChunkQueue(max_seconds=1, sample_rate=16000, channels=1)
        asr = BlockingAsr()
        worker = asyncio.create_task(_send_asr_audio_worker(asr, queue))
        try:
            await queue.push(b"\x00\x00" * 320)
            await asyncio.wait_for(asr.started.wait(), timeout=1)
            await queue.push(b"\x00\x00" * 16000)
            try:
                await queue.push(b"\x00\x00" * 320)
            except BufferError as exc:
                assert "full" in str(exc)
            else:
                raise AssertionError("expected BufferError")
        finally:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker

    asyncio.run(run_scenario())


def test_text_adapter_removes_model_tags():
    text = normalize_asr_text("<|zh|> 打开 一号机器人 ")

    assert text == "打开 一号机器人"


def test_intent_request_uses_partner_parameter_shape():
    request = build_intent_request(
        text="  向前走  ",
        sn="stt_123",
        params=IntentParams(
            user_semantics=UserSemantics(
                client_id="工匠汇",
                enterprise_id="ent_1",
                device_id="robot_1",
            ),
            current_time="星期二 2026-05-26 10:00:00",
            location="苏州",
        ),
    )

    assert request.model_dump() == {
        "sn": "stt_123",
        "query": "向前走",
        "user_semantics": {
            "client_id": "工匠汇",
            "enterprise_id": "ent_1",
            "device_id": "robot_1",
            "deviceid": None,
        },
        "current_time": "星期二 2026-05-26 10:00:00",
        "location": "苏州",
    }


def test_command_response_uses_partner_output_shape():
    response = command_to_partner_response(
        RobotCommand(
            intent="move_forward",
            raw_text="向前走",
            params={"matched_text": "向前"},
            confidence=1.0,
            parser="rule",
        )
    )

    assert response.model_dump() == {
        "status": 1,
        "error": "",
        "nlp": [
            {
                "english_domain": "robot_control",
                "slots": {"matched_text": "向前"},
                "source": "cloud_stt",
                "intent": "move_forward",
                "feed": {"image": [], "video": [], "audio": []},
                "answer": "向前走",
            }
        ],
        "msg": "返回成功",
    }


def test_unknown_command_response_is_no_result():
    response = command_to_partner_response(
        RobotCommand(intent="unknown", raw_text="今天天气不错")
    )

    assert response.model_dump() == {
        "status": 0,
        "error": "",
        "nlp": [],
        "msg": "未识别到可执行意图",
    }

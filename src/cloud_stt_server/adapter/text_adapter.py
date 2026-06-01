import re

from cloud_stt_server.command.models import (
    IntentNlpResult,
    IntentParams,
    IntentRecognitionRequest,
    IntentRecognitionResponse,
    RobotCommand,
)


def normalize_asr_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"<\|.*?\|>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_intent_request(
    *,
    text: str,
    sn: str,
    params: IntentParams,
) -> IntentRecognitionRequest:
    return IntentRecognitionRequest(
        sn=sn,
        query=normalize_asr_text(text),
        user_semantics=params.user_semantics,
        current_time=params.current_time,
        location=params.location,
    )


def command_to_partner_response(
    command: RobotCommand,
    *,
    english_domain: str = "robot_control",
    source: str = "cloud_stt",
) -> IntentRecognitionResponse:
    if not command.recognized:
        return IntentRecognitionResponse(
            status=0,
            error="",
            nlp=[],
            msg="未识别到可执行意图",
        )

    return IntentRecognitionResponse(
        status=1,
        error="",
        nlp=[
            IntentNlpResult(
                english_domain=english_domain,
                slots=command.params,
                source=source,
                intent=command.intent,
                answer=command.raw_text,
            )
        ],
        msg="返回成功",
    )

from typing import Literal

from pydantic import BaseModel, Field

from cloud_stt_server.command.models import IntentParams, IntentRecognitionResponse


class AudioParams(BaseModel):
    format: Literal["pcm_s16le", "opus"] = "opus"
    sample_rate: int = 16000
    channels: int = 1
    frame_duration_ms: int = 20


class VadParams(BaseModel):
    engine: Literal["fsmn"] = "fsmn"
    pre_roll_ms: int = 200


class AsrParams(BaseModel):
    provider: str = "doubao"
    hotword_id: str | None = None


class CreateSessionRequest(BaseModel):
    audio: AudioParams = Field(default_factory=AudioParams)
    vad: VadParams = Field(default_factory=VadParams)
    asr: AsrParams = Field(default_factory=AsrParams)
    intent: IntentParams = Field(default_factory=IntentParams)


class CreateSessionResponse(BaseModel):
    session_id: str
    websocket_url: str
    expires_in_seconds: int


class SessionStatusResponse(BaseModel):
    session_id: str
    audio: AudioParams
    vad: VadParams
    asr: AsrParams
    intent: IntentParams
    created_at: float
    expires_at: float
    websocket_attached: bool


class CommitMessage(BaseModel):
    type: Literal["commit"]


class SttPartialMessage(BaseModel):
    type: Literal["stt.partial"] = "stt.partial"
    text: str


class SttFinalMessage(BaseModel):
    type: Literal["stt.final"] = "stt.final"
    text: str
    intent: IntentRecognitionResponse | None = None


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    message: str

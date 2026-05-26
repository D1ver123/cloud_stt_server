from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class RobotCommand:
    intent: str
    raw_text: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    parser: str = "unknown"

    @property
    def recognized(self) -> bool:
        return self.intent != "unknown"


class UserSemantics(BaseModel):
    client_id: str = Field(default="工匠汇", description="Customer or client identifier.")
    enterprise_id: str | None = None
    device_id: str | None = None
    deviceid: str | None = Field(
        default=None,
        description="Compatibility alias for device_id.",
    )

    @property
    def normalized_device_id(self) -> str | None:
        return self.device_id or self.deviceid


class IntentParams(BaseModel):
    enabled: bool = True
    user_semantics: UserSemantics = Field(default_factory=UserSemantics)
    current_time: str | None = None
    location: str | None = None


class IntentRecognitionRequest(BaseModel):
    sn: str
    query: str
    user_semantics: UserSemantics
    current_time: str | None = None
    location: str | None = None


class IntentFeed(BaseModel):
    image: list[str] = Field(default_factory=list)
    video: list[str] = Field(default_factory=list)
    audio: list[str] = Field(default_factory=list)


class IntentNlpResult(BaseModel):
    english_domain: str
    slots: dict[str, Any] = Field(default_factory=dict)
    source: str
    intent: str
    feed: IntentFeed = Field(default_factory=IntentFeed)
    answer: str


class IntentRecognitionResponse(BaseModel):
    status: int
    error: str = ""
    nlp: list[IntentNlpResult] = Field(default_factory=list)
    msg: str

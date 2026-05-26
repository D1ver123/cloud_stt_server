from dataclasses import dataclass, field
import time
import uuid

from cloud_stt_server.command.models import IntentParams
from cloud_stt_server.protocol import AsrParams, AudioParams, VadParams


@dataclass
class SttSession:
    session_id: str
    audio: AudioParams
    vad: VadParams
    asr: AsrParams
    intent: IntentParams
    created_at: float
    expires_at: float
    websocket_attached: bool = False
    final_text: str = ""
    partial_text: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


class SessionStore:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, SttSession] = {}

    def create(
        self,
        audio: AudioParams,
        vad: VadParams,
        asr: AsrParams,
        intent: IntentParams,
    ) -> SttSession:
        self.cleanup_expired()
        now = time.time()
        session_id = f"stt_{uuid.uuid4().hex}"
        session = SttSession(
            session_id=session_id,
            audio=audio,
            vad=vad,
            asr=asr,
            intent=intent,
            created_at=now,
            expires_at=now + self.ttl_seconds,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> SttSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.expired:
            self._sessions.pop(session_id, None)
            return None
        return session

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def cleanup_expired(self) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.expired
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

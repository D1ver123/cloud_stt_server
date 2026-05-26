import asyncio
from collections.abc import AsyncIterator
import contextlib
from dataclasses import dataclass
import json
import urllib.error
import urllib.parse
import urllib.request

from cloud_stt_client.config import AsrConfig, AudioConfig, IntentConfig, VadConfig


@dataclass(frozen=True)
class SttSession:
    session_id: str
    websocket_url: str
    expires_in_seconds: int | None = None


class RestSessionClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def create_session(
        self,
        audio: AudioConfig,
        vad: VadConfig,
        asr: AsrConfig,
        intent: IntentConfig | None = None,
    ) -> SttSession:
        intent = intent or IntentConfig()
        payload = {
            "audio": {
                "format": audio.format,
                "sample_rate": audio.sample_rate,
                "channels": audio.channels,
                "frame_duration_ms": audio.frame_duration_ms,
            },
            "vad": {
                "engine": vad.engine,
                "pre_roll_ms": vad.pre_roll_ms,
            },
            "asr": {
                "provider": asr.provider,
            },
            "intent": {
                "enabled": intent.enabled,
                "user_semantics": {
                    "client_id": intent.user_semantics.client_id,
                    "enterprise_id": intent.user_semantics.enterprise_id,
                    "device_id": intent.user_semantics.device_id,
                },
                "current_time": intent.current_time,
                "location": intent.location,
            },
        }
        if asr.hotword_id:
            payload["asr"]["hotword_id"] = asr.hotword_id
        return await asyncio.to_thread(self._post_session, payload)

    def _post_session(self, payload: dict) -> SttSession:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/stt/v1/sessions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"REST session creation failed: {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"REST session creation failed: {exc}") from exc

        parsed = json.loads(body)
        return SttSession(
            session_id=str(parsed["session_id"]),
            websocket_url=str(parsed["websocket_url"]),
            expires_in_seconds=parsed.get("expires_in_seconds"),
        )


class SttWebSocketClient:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.websocket = None

    async def __aenter__(self) -> "SttWebSocketClient":
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets is required. Install with: pip install websockets") from exc

        self.websocket = await websockets.connect(
            self.websocket_url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
            max_size=10 * 1024 * 1024,
            compression=None,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.websocket is not None:
            with contextlib.suppress(Exception):
                await self.websocket.close()
            self.websocket = None

    async def send_audio(self, data: bytes) -> None:
        if self.websocket is None:
            raise RuntimeError("WebSocket is not connected")
        try:
            await self.websocket.send(data)
        except Exception as exc:
            if _is_websocket_closed(exc):
                raise RuntimeError(f"WebSocket closed while sending audio: {exc}") from exc
            raise

    async def commit(self) -> None:
        if self.websocket is None:
            raise RuntimeError("WebSocket is not connected")
        try:
            await self.websocket.send(json.dumps({"type": "commit"}, ensure_ascii=False))
        except Exception as exc:
            if _is_websocket_closed(exc):
                raise RuntimeError(f"WebSocket closed while sending commit: {exc}") from exc
            raise

    async def events(self) -> AsyncIterator[dict]:
        if self.websocket is None:
            raise RuntimeError("WebSocket is not connected")
        try:
            async for message in self.websocket:
                if isinstance(message, bytes):
                    continue
                try:
                    yield json.loads(message)
                except json.JSONDecodeError:
                    yield {"type": "error", "message": "invalid json from server"}
        except Exception as exc:
            if _is_websocket_closed(exc):
                yield {"type": "error", "message": f"websocket closed: {exc}"}
                return
            raise


def websocket_url_with_session(base_ws_url: str, session_id: str) -> str:
    parsed = urllib.parse.urlparse(base_ws_url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query["session_id"] = session_id
    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(query))
    )


def _is_websocket_closed(exc: Exception) -> bool:
    try:
        import websockets
    except ImportError:
        return False
    return isinstance(exc, websockets.ConnectionClosed)

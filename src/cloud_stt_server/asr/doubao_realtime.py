import asyncio
import contextlib
from dataclasses import dataclass
import gzip
import inspect
import json
import uuid

from cloud_stt_server.adapter.text_adapter import normalize_asr_text
from cloud_stt_server.asr.base import AsrEventCallback, RealtimeAsr
from cloud_stt_server.config import DoubaoAsrConfig


PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001

FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_REQUEST = 0b0010
FULL_SERVER_RESPONSE = 0b1001
SERVER_ERROR_RESPONSE = 0b1111

NO_SEQUENCE = 0b0000
POS_SEQUENCE = 0b0001
NEG_SEQUENCE = 0b0010
NEG_WITH_SEQUENCE = 0b0011

NO_SERIALIZATION = 0b0000
JSON_SERIALIZATION = 0b0001

NO_COMPRESSION = 0b0000
GZIP_COMPRESSION = 0b0001


@dataclass(frozen=True)
class DoubaoAudioParams:
    format: str = "pcm"
    sample_rate: int = 16000
    bits: int = 16
    channels: int = 1
    codec: str = "raw"
    packet_duration_ms: int = 200

    @property
    def packet_bytes(self) -> int:
        return (
            self.sample_rate
            * self.channels
            * (self.bits // 8)
            * self.packet_duration_ms
            // 1000
        )


@dataclass(frozen=True)
class DoubaoFrame:
    message_type: int
    flags: int
    serialization: int
    compression: int
    sequence: int | None
    error_code: int | None
    payload: bytes | dict | None

    @property
    def is_final(self) -> bool:
        return self.flags in {NEG_SEQUENCE, NEG_WITH_SEQUENCE}


class DoubaoRealtimeAsr(RealtimeAsr):
    """Realtime ASR provider for Volcengine Doubao streaming ASR 2.0."""

    def __init__(
        self,
        config: DoubaoAsrConfig,
        audio: DoubaoAudioParams,
        on_event: AsrEventCallback,
        hotword_id: str | None = None,
    ):
        config.validate()
        self.config = config
        self.audio = audio
        self.on_event = on_event
        self.hotword_id = hotword_id
        self._websocket = None
        self._receive_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._started = False
        self._completed = asyncio.Event()
        self._final_text = ""
        self._sequence = 1
        self._pending_audio = bytearray()

    async def start(self) -> None:
        if self._started:
            return
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError(
                "websockets is required. Install with: pip install websockets"
            ) from exc

        request_id = str(uuid.uuid4())
        self._completed = asyncio.Event()
        self._final_text = ""
        self._sequence = 1
        self._pending_audio.clear()
        self._websocket = await websockets.connect(
            self.config.endpoint,
            **_websocket_connect_kwargs(
                websockets,
                self.config.build_headers(request_id),
            ),
        )
        self._receive_task = asyncio.create_task(self._receive_loop())
        await self._send_frame(
            FULL_CLIENT_REQUEST,
            POS_SEQUENCE,
            JSON_SERIALIZATION,
            GZIP_COMPRESSION,
            _json_payload(self._request_payload()),
            sequence=self._next_sequence(),
        )
        self._started = True
        self.on_event({"type": "asr.start", "provider": "doubao"})

    async def send_audio(self, data: bytes) -> None:
        if not self._started or self._websocket is None:
            raise RuntimeError("Doubao ASR recognition is not started")
        if not data:
            return
        async with self._lock:
            self._pending_audio.extend(data)
            packet_bytes = max(self.audio.packet_bytes, 1)
            while len(self._pending_audio) >= packet_bytes:
                chunk = bytes(self._pending_audio[:packet_bytes])
                del self._pending_audio[:packet_bytes]
                await self._send_audio_frame(chunk, final=False)

    async def stop(self) -> str:
        if self._websocket is None:
            return self._final_text
        try:
            if self._started:
                async with self._lock:
                    final_chunk = bytes(self._pending_audio)
                    self._pending_audio.clear()
                    with contextlib.suppress(Exception):
                        await self._send_audio_frame(final_chunk, final=True)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._completed.wait(), timeout=10.0)
        finally:
            self._started = False
            websocket = self._websocket
            self._websocket = None
            if websocket is not None:
                with contextlib.suppress(Exception):
                    await websocket.close()
            if self._receive_task is not None:
                self._receive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._receive_task
                self._receive_task = None
        return self._final_text

    async def _send_audio_frame(self, data: bytes, final: bool) -> None:
        await self._send_frame(
            AUDIO_ONLY_REQUEST,
            NEG_WITH_SEQUENCE if final else POS_SEQUENCE,
            NO_SERIALIZATION,
            GZIP_COMPRESSION,
            gzip.compress(data),
            sequence=-self._next_sequence() if final else self._next_sequence(),
        )

    async def _send_frame(
        self,
        message_type: int,
        flags: int,
        serialization: int,
        compression: int,
        payload: bytes,
        sequence: int | None = None,
    ) -> None:
        if self._websocket is None:
            raise RuntimeError("Doubao ASR websocket is not connected")
        frame = bytearray(
            _build_header(
                message_type=message_type,
                flags=flags,
                serialization=serialization,
                compression=compression,
            )
        )
        if flags in {POS_SEQUENCE, NEG_WITH_SEQUENCE}:
            if sequence is None:
                raise ValueError("sequence is required for this frame flag")
            frame.extend(int(sequence).to_bytes(4, "big", signed=True))
        frame.extend(len(payload).to_bytes(4, "big", signed=False))
        frame.extend(payload)
        await self._websocket.send(bytes(frame))

    async def _receive_loop(self) -> None:
        try:
            async for message in self._websocket:
                if not isinstance(message, bytes):
                    continue
                frame = parse_doubao_frame(message)
                if frame.message_type == SERVER_ERROR_RESPONSE:
                    self.on_event({"type": "error", "message": _format_error_frame(frame)})
                    self._completed.set()
                    return
                if frame.message_type != FULL_SERVER_RESPONSE:
                    continue
                if isinstance(frame.payload, dict):
                    self._handle_response(frame.payload, force_final=frame.is_final)
                if frame.is_final:
                    self._completed.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._started:
                self.on_event(
                    {
                        "type": "error",
                        "message": f"Doubao ASR receive failed: {exc}",
                    }
                )
            self._completed.set()
        finally:
            self._completed.set()

    def _handle_response(self, payload: dict, force_final: bool = False) -> None:
        if _is_error_payload(payload):
            self.on_event({"type": "error", "message": _format_error_payload(payload)})
            return

        text, is_final = _extract_text(payload)
        if not text:
            return
        if is_final or force_final:
            self._final_text = text
            self.on_event({"type": "stt.final", "text": text})
        else:
            self.on_event({"type": "stt.partial", "text": text})

    def _request_payload(self) -> dict:
        request: dict = {
            "model_name": self.config.model_name,
            "enable_itn": self.config.enable_itn,
            "enable_punc": self.config.enable_punc,
            "enable_ddc": self.config.enable_ddc,
            "show_utterances": self.config.show_utterances,
            "enable_nonstream": self.config.enable_nonstream,
            "end_window_size": self.config.end_window_size,
        }
        if self.hotword_id:
            request["corpus"] = {"boosting_table_id": self.hotword_id}

        audio = {
            "format": self.audio.format,
            "rate": self.audio.sample_rate,
            "bits": self.audio.bits,
            "channel": self.audio.channels,
            "codec": self.audio.codec,
        }
        if self.config.language is not None:
            audio["language"] = self.config.language

        return {
            "user": {"uid": self.config.uid},
            "audio": audio,
            "request": request,
        }

    def _next_sequence(self) -> int:
        sequence = self._sequence
        self._sequence += 1
        return sequence


def _build_header(
    message_type: int,
    flags: int,
    serialization: int,
    compression: int,
) -> bytes:
    return bytes(
        [
            (PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE,
            (message_type << 4) | flags,
            (serialization << 4) | compression,
            0x00,
        ]
    )


def _json_payload(payload: dict) -> bytes:
    return gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def parse_doubao_frame(data: bytes) -> DoubaoFrame:
    if len(data) < 8:
        raise ValueError("Doubao ASR frame is too short")
    header_size = (data[0] & 0x0F) * 4
    if header_size < 4 or len(data) < header_size + 4:
        raise ValueError("Doubao ASR frame header is invalid")

    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    serialization = data[2] >> 4
    compression = data[2] & 0x0F
    offset = header_size
    sequence = None
    error_code = None

    if message_type == SERVER_ERROR_RESPONSE:
        if len(data) < offset + 8:
            raise ValueError("Doubao ASR error frame is too short")
        error_code = int.from_bytes(data[offset : offset + 4], "big", signed=True)
        offset += 4
    elif flags in {POS_SEQUENCE, NEG_WITH_SEQUENCE}:
        if len(data) < offset + 8:
            raise ValueError("Doubao ASR sequence frame is too short")
        sequence = int.from_bytes(data[offset : offset + 4], "big", signed=True)
        offset += 4

    payload_size = int.from_bytes(data[offset : offset + 4], "big", signed=False)
    offset += 4
    payload_bytes = data[offset : offset + payload_size]
    if len(payload_bytes) != payload_size:
        raise ValueError("Doubao ASR frame payload is truncated")

    if compression == GZIP_COMPRESSION and payload_bytes:
        payload_bytes = gzip.decompress(payload_bytes)

    payload: bytes | dict | None = payload_bytes
    if serialization == JSON_SERIALIZATION and payload_bytes:
        payload = json.loads(payload_bytes.decode("utf-8"))
        payload = _unwrap_payload_message(payload)
    elif not payload_bytes:
        payload = None

    return DoubaoFrame(
        message_type=message_type,
        flags=flags,
        serialization=serialization,
        compression=compression,
        sequence=sequence,
        error_code=error_code,
        payload=payload,
    )


def _unwrap_payload_message(payload: dict) -> dict:
    payload_msg = payload.get("payload_msg")
    if isinstance(payload_msg, str):
        with contextlib.suppress(json.JSONDecodeError):
            decoded = json.loads(payload_msg)
            if isinstance(decoded, dict):
                return decoded
    return payload


def _extract_text(payload: dict) -> tuple[str, bool]:
    result = payload.get("result", payload)
    if isinstance(result, list):
        result = result[-1] if result else {}
    if not isinstance(result, dict):
        return "", False

    utterances = result.get("utterances") or payload.get("utterances") or []
    definite_texts = [
        normalize_asr_text(str(item.get("text", "")))
        for item in utterances
        if isinstance(item, dict) and item.get("definite") is True
    ]
    if definite_texts:
        return "".join(definite_texts), True

    text = normalize_asr_text(str(result.get("text") or payload.get("text") or ""))
    is_final = any(
        bool(result.get(key) or payload.get(key))
        for key in ("definite", "final", "is_final")
    )
    return text, is_final


def _is_error_payload(payload: dict) -> bool:
    code = payload.get("code")
    return code not in (None, 0, 1000, 20000000, "0", "1000", "20000000")


def _format_error_payload(payload: dict) -> str:
    code = payload.get("code", "")
    message = payload.get("message") or payload.get("msg") or payload
    return f"Doubao ASR error {code}: {message}"


def _format_error_frame(frame: DoubaoFrame) -> str:
    if isinstance(frame.payload, dict):
        return _format_error_payload({"code": frame.error_code, **frame.payload})
    if isinstance(frame.payload, bytes):
        detail = frame.payload.decode("utf-8", errors="replace")
    else:
        detail = ""
    return f"Doubao ASR error {frame.error_code}: {detail}"


def _websocket_connect_kwargs(websockets, headers: dict[str, str]) -> dict:
    kwargs = {
        "ping_interval": 20,
        "ping_timeout": 20,
        "close_timeout": 10,
        "max_size": 10 * 1024 * 1024,
        "compression": None,
    }
    parameters = inspect.signature(websockets.connect).parameters
    if "additional_headers" in parameters:
        kwargs["additional_headers"] = headers
    elif "extra_headers" in parameters:
        kwargs["extra_headers"] = headers
    else:
        kwargs["extra_headers"] = headers
    if "proxy" in parameters:
        kwargs["proxy"] = None
    return kwargs

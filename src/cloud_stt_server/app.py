import json
from urllib.parse import urlparse
import asyncio
import contextlib
import logging

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

from cloud_stt_server.adapter import build_intent_request, command_to_partner_response
from cloud_stt_server.asr.factory import SUPPORTED_ASR_PROVIDERS, create_realtime_asr
from cloud_stt_server.audio.decoder import AudioDecoder
from cloud_stt_server.audio.queue import AsyncAudioChunkQueue
from cloud_stt_server.audio.rolling_buffer import RollingAudioBuffer
from cloud_stt_server.command import RuleCommandParser
from cloud_stt_server.config import AppConfig
from cloud_stt_server.protocol import (
    CreateSessionRequest,
    CreateSessionResponse,
    ErrorMessage,
    SessionStatusResponse,
    SttFinalMessage,
)
from cloud_stt_server.sessions import SessionStore
from cloud_stt_server.vad.fsmn_vad import FsmnVadTracker


config = AppConfig()
sessions = SessionStore(ttl_seconds=300)
app = FastAPI(title="xiaozhi-cloud-stt")
logger = logging.getLogger(__name__)
command_parser = RuleCommandParser()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/stt/v1/sessions", response_model=CreateSessionResponse)
async def create_session(
    payload: CreateSessionRequest,
    request: Request,
) -> CreateSessionResponse:
    audio = payload.audio
    if audio.format not in config.audio.supported_formats:
        raise HTTPException(status_code=400, detail="unsupported audio format")
    if audio.sample_rate != config.audio.sample_rate:
        raise HTTPException(status_code=400, detail="only 16000 Hz audio is supported")
    if audio.channels != config.audio.channels:
        raise HTTPException(status_code=400, detail="only mono audio is supported")
    if payload.vad.engine != "fsmn":
        raise HTTPException(status_code=400, detail="only fsmn vad is supported")
    if payload.asr.provider not in SUPPORTED_ASR_PROVIDERS:
        raise HTTPException(status_code=400, detail="unsupported asr provider")

    session = sessions.create(
        audio=audio,
        vad=payload.vad,
        asr=payload.asr,
        intent=payload.intent,
    )
    websocket_url = _build_websocket_url(request, session.session_id)
    return CreateSessionResponse(
        session_id=session.session_id,
        websocket_url=websocket_url,
        expires_in_seconds=sessions.ttl_seconds,
    )


@app.get("/stt/v1/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session(session_id: str) -> SessionStatusResponse:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionStatusResponse(
        session_id=session.session_id,
        audio=session.audio,
        vad=session.vad,
        asr=session.asr,
        intent=session.intent,
        created_at=session.created_at,
        expires_at=session.expires_at,
        websocket_attached=session.websocket_attached,
    )


@app.delete("/stt/v1/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    return {"deleted": sessions.delete(session_id)}


@app.websocket("/stt/v1/stream")
async def stt_stream(websocket: WebSocket) -> None:
    session_id = websocket.query_params.get("session_id")
    if not session_id:
        await websocket.accept()
        await websocket.send_json(ErrorMessage(message="missing session_id").model_dump())
        await websocket.close()
        return

    session = sessions.get(session_id)
    if session is None:
        await websocket.accept()
        await websocket.send_json(
            ErrorMessage(message="invalid or expired session_id").model_dump()
        )
        await websocket.close()
        return

    await websocket.accept()
    session.websocket_attached = True
    receive_task = None
    event_task = None
    sender_task = None

    async def send_event(event: dict) -> None:
        if event.get("type") == "stt.partial":
            session.partial_text = str(event.get("text", ""))
        elif event.get("type") == "stt.final":
            session.final_text = str(event.get("text", ""))
            event = _attach_intent_result(event, session)
        await websocket.send_json(event)

    event_queue: asyncio.Queue[dict] = asyncio.Queue()

    def on_asr_event(event: dict) -> None:
        event_queue.put_nowait(event)

    try:
        decoder = AudioDecoder(
            audio_format=session.audio.format,
            sample_rate=session.audio.sample_rate,
            channels=session.audio.channels,
            frame_duration_ms=session.audio.frame_duration_ms,
        )
        rolling = RollingAudioBuffer(
            max_ms=session.vad.pre_roll_ms,
            sample_rate=session.audio.sample_rate,
            channels=session.audio.channels,
        )
        queue = AsyncAudioChunkQueue(
            max_seconds=config.audio.max_queue_seconds,
            sample_rate=session.audio.sample_rate,
            channels=session.audio.channels,
        )
        vad = FsmnVadTracker(config.fsmn_vad)
        asr = create_realtime_asr(
            provider=session.asr.provider,
            config=config,
            on_event=on_asr_event,
            hotword_id=session.asr.hotword_id,
        )
        async with asr:
            sender_task = asyncio.create_task(_send_asr_audio_worker(asr, queue))
            receive_task = asyncio.create_task(websocket.receive())
            event_task = asyncio.create_task(event_queue.get())
            while True:
                done, pending = await asyncio.wait(
                    {receive_task, event_task, sender_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if sender_task in done:
                    exc = sender_task.exception()
                    message = str(exc) if exc is not None else "ASR sender stopped"
                    await send_event(ErrorMessage(message=message).model_dump())
                    break

                if event_task in done:
                    event = event_task.result()
                    await send_event(event)
                    event_task = asyncio.create_task(event_queue.get())
                    if event.get("type") == "stt.final":
                        continue

                if receive_task not in done:
                    continue

                message = receive_task.result()
                receive_task = asyncio.create_task(websocket.receive())
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    try:
                        pcm = decoder.decode(message["bytes"])
                        state = vad.observe(pcm)
                        if not state.speech_start:
                            rolling.append(pcm)
                            continue
                        preroll = rolling.read_all()
                        if preroll:
                            await queue.push(preroll)
                            rolling.clear()
                        await queue.push(pcm)
                        if state.speech_end:
                            await _wait_asr_queue_drained(queue, sender_task)
                            text = await asr.stop()
                            if text and text != session.final_text:
                                await send_event(SttFinalMessage(text=text).model_dump())
                            break
                    except (BufferError, RuntimeError, ValueError) as exc:
                        await send_event(ErrorMessage(message=str(exc)).model_dump())
                        break
                elif message.get("text") is not None:
                    try:
                        payload = json.loads(message["text"])
                    except json.JSONDecodeError:
                        await send_event(ErrorMessage(message="invalid json").model_dump())
                        continue
                    if payload.get("type") == "commit":
                        await _wait_asr_queue_drained(queue, sender_task)
                        text = await asr.stop()
                        if text and text != session.final_text:
                            await send_event(SttFinalMessage(text=text).model_dump())
                        break
                    await send_event(
                        ErrorMessage(
                            message=f"unsupported message type: {payload.get('type')}"
                        ).model_dump()
                    )
    except WebSocketDisconnect:
        return
    except RuntimeError as exc:
        logger.exception("STT WebSocket runtime error")
        with contextlib.suppress(Exception):
            await send_event(ErrorMessage(message=str(exc)).model_dump())
    except Exception as exc:
        logger.exception("STT WebSocket failed")
        with contextlib.suppress(Exception):
            await send_event(
                ErrorMessage(message=f"{type(exc).__name__}: {exc}").model_dump()
            )
    finally:
        for task in (receive_task, event_task, sender_task):
            if task is not None and not task.done():
                task.cancel()
        session.websocket_attached = False
        sessions.delete(session.session_id)


def _build_websocket_url(request: Request, session_id: str) -> str:
    parsed = urlparse(str(request.base_url))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    base = f"{scheme}://{parsed.netloc}"
    return f"{base}/stt/v1/stream?session_id={session_id}"


def _attach_intent_result(event: dict, session) -> dict:
    if not session.intent.enabled or event.get("intent") is not None:
        return event

    text = str(event.get("text", ""))
    request = build_intent_request(
        text=text,
        sn=session.session_id,
        params=session.intent,
    )
    command = command_parser.parse_request(request)
    response = command_to_partner_response(command)
    enriched = dict(event)
    enriched["intent"] = response.model_dump()
    return enriched


async def _send_asr_audio_worker(asr, queue: AsyncAudioChunkQueue) -> None:
    while True:
        pcm = await queue.get()
        try:
            await asr.send_audio(pcm)
        finally:
            queue.task_done()


async def _wait_asr_queue_drained(
    queue: AsyncAudioChunkQueue,
    sender_task: asyncio.Task,
) -> None:
    join_task = asyncio.create_task(queue.join())
    done, pending = await asyncio.wait(
        {join_task, sender_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if sender_task in done:
        join_task.cancel()
        exc = sender_task.exception()
        if exc is not None:
            raise RuntimeError(str(exc)) from exc
        raise RuntimeError("ASR sender stopped")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=config.server.host, port=config.server.port)

import argparse
import asyncio
import ctypes
import ctypes.util
import json
import os
import platform
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate an external robot: PCM input -> Opus encode -> WebSocket stream."
    )
    parser.add_argument("--server", default="http://127.0.0.1:8011")
    parser.add_argument("--pcm", type=Path, default=Path("robot_audio.pcm"))
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--frame-duration-ms", type=int, default=20)
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--client-id", default="external_robot")
    parser.add_argument("--enterprise-id", default="ent_1")
    parser.add_argument("--device-id", default="robot_1")
    parser.add_argument("--location", default="")
    parser.add_argument("--current-time", default="")
    parser.add_argument("--opus-lib")
    parser.add_argument(
        "--no-wait-asr-start",
        action="store_true",
        help="Start streaming immediately after WebSocket connection.",
    )
    return parser.parse_args()


def setup_opus(explicit_path: str | None = None) -> None:
    errors: list[str] = []
    for candidate in opus_candidates(explicit_path):
        try:
            if platform.system().lower().startswith("win"):
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(str(candidate.parent))
                os.environ["PATH"] = str(candidate.parent) + os.pathsep + os.environ.get(
                    "PATH", ""
                )
            patch_find_library("opus", str(candidate))
            ctypes.CDLL(str(candidate))
            return
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")

    system_path = ctypes.util.find_library("opus")
    if system_path:
        try:
            ctypes.CDLL(system_path)
            return
        except OSError as exc:
            errors.append(f"{system_path}: {exc}")

    detail = "; ".join(errors) if errors else "no libopus candidate found"
    raise RuntimeError(f"Opus support requires native libopus. Detail: {detail}")


def opus_candidates(explicit_path: str | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    env_path = os.getenv("CLOUD_STT_OPUS_LIB")
    if env_path:
        candidates.append(Path(env_path))

    root = Path(__file__).resolve().parent
    candidates.append(root / relative_opus_path())

    conda_prefix = os.getenv("CONDA_PREFIX")
    prefixes = [Path(conda_prefix)] if conda_prefix else []
    prefixes.append(Path(sys.prefix))
    for prefix in dict.fromkeys(prefixes):
        if platform.system().lower().startswith("win"):
            candidates.append(prefix / "Library/bin/opus.dll")
        elif platform.system().lower() == "darwin":
            candidates.append(prefix / "lib/libopus.dylib")
        else:
            candidates.append(prefix / "lib/libopus.so")

    return [path for path in candidates if path.exists()]


def relative_opus_path() -> Path:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "arm64" if "arm" in machine or "aarch64" in machine else "x64"
    if system.startswith("win"):
        return Path("libs/libopus/win/x64/opus.dll")
    if system == "darwin":
        return Path(f"libs/libopus/mac/{arch}/libopus.dylib")
    return Path(f"libs/libopus/linux/{arch}/libopus.so")


def patch_find_library(name: str, path: str) -> None:
    original = ctypes.util.find_library

    def patched(value: str) -> str | None:
        if value == name:
            return path
        return original(value)

    ctypes.util.find_library = patched


def create_session(args: argparse.Namespace) -> dict:
    payload = {
        "audio": {
            "format": "opus",
            "sample_rate": args.sample_rate,
            "channels": args.channels,
            "frame_duration_ms": args.frame_duration_ms,
        },
        "vad": {
            "engine": "fsmn",
            "pre_roll_ms": 200,
        },
        "asr": {
            "provider": "doubao",
        },
        "intent": {
            "enabled": True,
            "user_semantics": {
                "client_id": args.client_id,
                "enterprise_id": args.enterprise_id,
                "device_id": args.device_id,
            },
            "current_time": args.current_time,
            "location": args.location,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{args.server.rstrip('/')}/stt/v1/sessions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"create session failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"create session failed: {exc}") from exc


def iter_pcm_frames(path: Path, frame_bytes: int):
    with path.open("rb") as file:
        while True:
            frame = file.read(frame_bytes)
            if not frame:
                break
            if len(frame) < frame_bytes:
                frame += b"\x00" * (frame_bytes - len(frame))
            yield frame


def elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)


async def receive_events(
    websocket,
    started_at: float,
    timing: dict,
    asr_started: asyncio.Event,
) -> None:
    async for message in websocket:
        if isinstance(message, bytes):
            continue
        print(f"SERVER => {message}", flush=True)
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            continue

        if event.get("type") == "asr.start":
            timing["asr_start_ms"] = elapsed_ms(started_at)
            asr_started.set()

        text = str(event.get("text", ""))
        if text and "first_char_recognized_ms" not in timing:
            timing["first_char"] = text[0]
            timing["first_char_recognized_ms"] = elapsed_ms(started_at)
            if "_first_audio_sent_at" in timing:
                timing["first_audio_to_first_char_recognized_ms"] = round(
                    (time.perf_counter() - timing["_first_audio_sent_at"]) * 1000,
                    2,
                )
            print(f"ROBOT_FIRST_CHAR => {text[0]}", flush=True)
            timing["first_char_output_ms"] = elapsed_ms(started_at)
            if "_first_audio_sent_at" in timing:
                timing["first_audio_to_first_char_output_ms"] = round(
                    (time.perf_counter() - timing["_first_audio_sent_at"]) * 1000,
                    2,
                )
            timing["recognize_to_output_delta_ms"] = round(
                timing["first_char_output_ms"] - timing["first_char_recognized_ms"],
                2,
            )
            public_timing = {
                key: value for key, value in timing.items() if not key.startswith("_")
            }
            print(
                f"TIMING => {json.dumps(public_timing, ensure_ascii=False)}",
                flush=True,
            )

        if event.get("type") in {"stt.final", "error"}:
            return


async def run(args: argparse.Namespace) -> None:
    started_at = time.perf_counter()
    timing: dict = {}
    if not args.pcm.exists():
        raise FileNotFoundError(f"PCM file not found: {args.pcm}")
    if args.sample_rate != 16000 or args.channels != 1:
        raise ValueError("server currently requires 16000 Hz mono audio")

    setup_opus(args.opus_lib)
    try:
        import opuslib
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "This script requires opuslib and websockets. Install them first."
        ) from exc

    frame_samples = args.sample_rate * args.frame_duration_ms // 1000
    frame_bytes = frame_samples * args.channels * 2
    encoder = opuslib.Encoder(
        args.sample_rate,
        args.channels,
        opuslib.APPLICATION_VOIP,
    )

    session = create_session(args)
    websocket_url = session["websocket_url"]
    print(f"SESSION => {json.dumps(session, ensure_ascii=False)}", flush=True)

    async with websockets.connect(websocket_url, compression=None) as websocket:
        asr_started = asyncio.Event()
        receive_task = asyncio.create_task(
            receive_events(websocket, started_at, timing, asr_started)
        )
        sent_frames = 0

        if not args.no_wait_asr_start:
            await asyncio.wait_for(asr_started.wait(), timeout=10)

        for pcm_frame in iter_pcm_frames(args.pcm, frame_bytes):
            opus_packet = encoder.encode(pcm_frame, frame_samples)
            await websocket.send(opus_packet)
            if sent_frames == 0:
                timing["first_audio_send_ms"] = elapsed_ms(started_at)
                timing["_first_audio_sent_at"] = time.perf_counter()
            sent_frames += 1
            if args.realtime:
                await asyncio.sleep(args.frame_duration_ms / 1000)

        await websocket.send(json.dumps({"type": "commit"}, ensure_ascii=False))
        timing["commit_sent_ms"] = elapsed_ms(started_at)
        print(f"CLIENT => sent {sent_frames} opus frames and commit", flush=True)

        try:
            await asyncio.wait_for(receive_task, timeout=20)
        except asyncio.TimeoutError:
            receive_task.cancel()
            raise TimeoutError("timed out waiting for stt.final or error")


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

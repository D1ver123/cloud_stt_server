import argparse
import asyncio
import json
from pathlib import Path

from cloud_stt_client.audio.devices import list_input_devices
from cloud_stt_client.audio.wav_source import iter_wav_frames
from cloud_stt_client.config import (
    AsrConfig,
    AudioConfig,
    ClientConfig,
    IntentConfig,
    UserSemanticsConfig,
    WakeWordConfig,
)
from cloud_stt_client.pipeline import VoiceSttClient


def _print_event(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False))


def _intent_config_from_args(args: argparse.Namespace) -> IntentConfig:
    return IntentConfig(
        enabled=not args.disable_intent,
        user_semantics=UserSemanticsConfig(
            client_id=args.intent_client_id,
            enterprise_id=args.intent_enterprise_id,
            device_id=args.intent_device_id,
        ),
        current_time=args.current_time,
        location=args.location,
    )


def _add_intent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--disable-intent", action="store_true")
    parser.add_argument("--intent-client-id", default="工匠汇")
    parser.add_argument("--intent-enterprise-id")
    parser.add_argument("--intent-device-id")
    parser.add_argument("--current-time")
    parser.add_argument("--location")


async def _stream(args: argparse.Namespace) -> None:
    audio = AudioConfig(
        format=args.audio_format,
        sample_rate=args.sample_rate,
        channels=1,
        frame_duration_ms=args.frame_duration_ms,
        device_id=args.device_id,
    )
    config = ClientConfig(
        rest_base_url=args.server,
        websocket_url=args.websocket_url,
        audio=audio,
        asr=AsrConfig(provider=args.asr_provider, hotword_id=args.hotword_id),
        wake_word=WakeWordConfig(
            enabled=args.wake_word,
            num_threads=args.wake_word_num_threads,
            provider=args.wake_word_provider,
            max_active_paths=args.wake_word_max_active_paths,
            keywords_score=args.wake_word_keywords_score,
            keywords_threshold=args.wake_word_keywords_threshold,
            num_trailing_blanks=args.wake_word_num_trailing_blanks,
            detection_cooldown_seconds=args.wake_word_cooldown,
            idle_timeout_seconds=args.wake_word_idle_timeout_seconds,
            interrupt_texts=tuple(args.wake_word_interrupt_texts),
        ),
        intent=_intent_config_from_args(args),
        queue_max_frames=args.queue_max_frames,
    )
    await VoiceSttClient(config).run(
        duration_seconds=args.duration,
        on_event=_print_event,
        on_timing=_print_event if args.timing else None,
    )


async def _stream_wav(args: argparse.Namespace) -> None:
    audio = AudioConfig(
        format=args.audio_format,
        sample_rate=args.sample_rate,
        channels=1,
        frame_duration_ms=args.frame_duration_ms,
    )
    config = ClientConfig(
        rest_base_url=args.server,
        websocket_url=args.websocket_url,
        audio=audio,
        asr=AsrConfig(provider=args.asr_provider, hotword_id=args.hotword_id),
        intent=_intent_config_from_args(args),
        queue_max_frames=args.queue_max_frames,
    )
    await VoiceSttClient(config).run_frames(
        iter_wav_frames(args.wav, audio),
        on_event=_print_event,
        realtime=args.realtime,
        on_timing=_print_event if args.timing else None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="cloud-stt user client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-devices", help="List input devices")
    list_parser.add_argument("--include-virtual", action="store_true")

    stream_parser = subparsers.add_parser("stream", help="Stream microphone audio")
    stream_parser.add_argument("--server", default="http://127.0.0.1:8000")
    stream_parser.add_argument("--websocket-url")
    stream_parser.add_argument("--device-id", type=int)
    stream_parser.add_argument(
        "--audio-format",
        choices=("pcm_s16le", "opus"),
        default="opus",
    )
    stream_parser.add_argument("--sample-rate", type=int, default=16000)
    stream_parser.add_argument("--frame-duration-ms", type=int, default=20)
    stream_parser.add_argument("--queue-max-frames", type=int, default=200)
    stream_parser.add_argument("--duration", type=float)
    stream_parser.add_argument(
        "--timing",
        action="store_true",
        help="Print client-side end-to-end timing events.",
    )
    stream_parser.add_argument("--asr-provider", default="dashscope")
    stream_parser.add_argument("--hotword-id")
    stream_parser.add_argument(
        "--wake-word",
        action="store_true",
        help="Wait for a local Sherpa-ONNX wake word before streaming audio.",
    )
    stream_parser.add_argument("--wake-word-num-threads", type=int, default=4)
    stream_parser.add_argument("--wake-word-provider", default="cpu")
    stream_parser.add_argument("--wake-word-max-active-paths", type=int, default=2)
    stream_parser.add_argument("--wake-word-keywords-score", type=float, default=1.8)
    stream_parser.add_argument("--wake-word-keywords-threshold", type=float, default=0.2)
    stream_parser.add_argument("--wake-word-num-trailing-blanks", type=int, default=1)
    stream_parser.add_argument("--wake-word-cooldown", type=float, default=1.5)
    stream_parser.add_argument(
        "--wake-word-idle-timeout-seconds",
        dest="wake_word_idle_timeout_seconds",
        type=float,
        default=60.0,
        help="Close the cloud STT stream after this many seconds without STT activity.",
    )
    stream_parser.add_argument(
        "--wake-word-interrupt-texts",
        nargs="*",
        default=["退出", "停下", "停止", "结束"],
        help="Wake-word detector texts that close the active STT stream.",
    )
    _add_intent_args(stream_parser)

    wav_parser = subparsers.add_parser("stream-wav", help="Stream a PCM WAV file")
    wav_parser.add_argument("wav", type=Path)
    wav_parser.add_argument("--server", default="http://127.0.0.1:8000")
    wav_parser.add_argument("--websocket-url")
    wav_parser.add_argument(
        "--audio-format",
        choices=("pcm_s16le", "opus"),
        default="opus",
    )
    wav_parser.add_argument("--sample-rate", type=int, default=16000)
    wav_parser.add_argument("--frame-duration-ms", type=int, default=20)
    wav_parser.add_argument("--queue-max-frames", type=int, default=200)
    wav_parser.add_argument(
        "--timing",
        action="store_true",
        help="Print client-side end-to-end timing events.",
    )
    wav_parser.add_argument("--asr-provider", default="dashscope")
    wav_parser.add_argument("--hotword-id")
    _add_intent_args(wav_parser)
    wav_parser.add_argument(
        "--realtime",
        action="store_true",
        help="Sleep between frames to mimic microphone realtime streaming.",
    )

    args = parser.parse_args()

    if args.command == "list-devices":
        for device in list_input_devices(include_virtual=args.include_virtual):
            print(
                f"{device.index}: {device.name} "
                f"({device.sample_rate}Hz, {device.channels}ch, {device.hostapi})"
            )
        return

    if args.command == "stream":
        asyncio.run(_stream(args))
    elif args.command == "stream-wav":
        asyncio.run(_stream_wav(args))


if __name__ == "__main__":
    main()

from cloud_stt_server.asr.base import AsrEventCallback, RealtimeAsr
from cloud_stt_server.asr.dashscope_realtime import (
    DashScopeAudioParams,
    DashScopeRealtimeAsr,
)
from cloud_stt_server.asr.doubao_realtime import DoubaoAudioParams, DoubaoRealtimeAsr
from cloud_stt_server.config import AppConfig


SUPPORTED_ASR_PROVIDERS = ("doubao", "dashscope")


def create_realtime_asr(
    provider: str,
    config: AppConfig,
    on_event: AsrEventCallback,
    hotword_id: str | None = None,
) -> RealtimeAsr:
    if provider == "doubao":
        return DoubaoRealtimeAsr(
            config=config.doubao_asr,
            audio=DoubaoAudioParams(
                format=config.doubao_asr.format,
                sample_rate=config.doubao_asr.sample_rate,
                bits=config.doubao_asr.bits,
                channels=config.doubao_asr.channels,
                codec=config.doubao_asr.codec,
                packet_duration_ms=config.doubao_asr.packet_duration_ms,
            ),
            on_event=on_event,
            hotword_id=hotword_id,
        )
    if provider == "dashscope":
        return DashScopeRealtimeAsr(
            config=config.dashscope_asr,
            audio=DashScopeAudioParams(
                format=config.dashscope_asr.format,
                sample_rate=config.dashscope_asr.sample_rate,
            ),
            on_event=on_event,
            hotword_id=hotword_id,
        )
    raise ValueError(f"unsupported asr provider: {provider}")

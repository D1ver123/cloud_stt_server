from cloud_stt_server.asr.base import AsrEventCallback, RealtimeAsr
from cloud_stt_server.asr.dashscope_realtime import (
    DashScopeAudioParams,
    DashScopeRealtimeAsr,
)
from cloud_stt_server.config import AppConfig


SUPPORTED_ASR_PROVIDERS = ("dashscope",)


def create_realtime_asr(
    provider: str,
    config: AppConfig,
    on_event: AsrEventCallback,
    hotword_id: str | None = None,
) -> RealtimeAsr:
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

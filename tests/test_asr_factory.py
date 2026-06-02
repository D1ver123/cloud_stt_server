from cloud_stt_server.asr.factory import create_realtime_asr
from cloud_stt_server.asr.dashscope_realtime import DashScopeRealtimeAsr
from cloud_stt_server.asr.doubao_realtime import DoubaoRealtimeAsr
from cloud_stt_server.config import AppConfig, DashScopeAsrConfig, DoubaoAsrConfig


def test_doubao_factory_creates_realtime_asr():
    config = AppConfig(doubao_asr=DoubaoAsrConfig(api_key="test_key"))

    asr = create_realtime_asr(
        provider="doubao",
        config=config,
        on_event=lambda event: None,
    )

    assert isinstance(asr, DoubaoRealtimeAsr)
    assert asr.config.resource_id == "volc.seedasr.sauc.duration"


def test_dashscope_factory_preserves_hotword_id():
    config = AppConfig(dashscope_asr=DashScopeAsrConfig(api_key="test_key"))

    asr = create_realtime_asr(
        provider="dashscope",
        config=config,
        on_event=lambda event: None,
        hotword_id="phrase_123",
    )

    assert isinstance(asr, DashScopeRealtimeAsr)
    assert asr.hotword_id == "phrase_123"

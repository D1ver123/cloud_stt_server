from dataclasses import dataclass


@dataclass(frozen=True)
class AudioConfig:
    format: str = "opus"
    sample_rate: int = 16000
    channels: int = 1
    frame_duration_ms: int = 20
    source_sample_rate: int | None = None
    source_channels: int | None = None
    device_id: int | None = None

    @property
    def frame_samples(self) -> int:
        return self.sample_rate * self.frame_duration_ms // 1000

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * self.channels * 2


@dataclass(frozen=True)
class VadConfig:
    engine: str = "fsmn"
    pre_roll_ms: int = 200


@dataclass(frozen=True)
class AsrConfig:
    provider: str = "dashscope"
    hotword_id: str | None = None


@dataclass(frozen=True)
class WakeWordConfig:
    enabled: bool = False
    model_dir: str = "models/wake_word"
    num_threads: int = 4
    provider: str = "cpu"
    max_active_paths: int = 2
    keywords_score: float = 1.8
    keywords_threshold: float = 0.2
    num_trailing_blanks: int = 1
    detection_cooldown_seconds: float = 1.5
    idle_timeout_seconds: float = 60.0
    interrupt_texts: tuple[str, ...] = ("退出", "停下", "停止", "结束")


@dataclass(frozen=True)
class UserSemanticsConfig:
    client_id: str = "工匠汇"
    enterprise_id: str | None = None
    device_id: str | None = None


@dataclass(frozen=True)
class IntentConfig:
    enabled: bool = True
    user_semantics: UserSemanticsConfig = UserSemanticsConfig()
    current_time: str | None = None
    location: str | None = None


@dataclass(frozen=True)
class ClientConfig:
    rest_base_url: str = "http://127.0.0.1:8000"
    websocket_url: str | None = None
    audio: AudioConfig = AudioConfig()
    vad: VadConfig = VadConfig()
    asr: AsrConfig = AsrConfig()
    wake_word: WakeWordConfig = WakeWordConfig()
    intent: IntentConfig = IntentConfig()
    queue_max_frames: int = 200
    send_commit_on_stop: bool = True

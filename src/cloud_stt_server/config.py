from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ServerConfig:
    host: str = os.getenv("CLOUD_STT_HOST", "0.0.0.0")
    port: int = int(os.getenv("CLOUD_STT_PORT", "8000"))


@dataclass(frozen=True)
class AudioConfig:
    supported_formats: tuple[str, ...] = ("pcm_s16le", "opus")
    sample_rate: int = 16000
    channels: int = 1
    frame_duration_ms: int = 20
    max_queue_seconds: int = 30


@dataclass(frozen=True)
class DashScopeAsrConfig:
    api_key: str | None = os.getenv("DASHSCOPE_API_KEY")
    model: str = os.getenv("DASHSCOPE_ASR_MODEL", "fun-asr-realtime")
    format: str = os.getenv("DASHSCOPE_ASR_FORMAT", "pcm")
    sample_rate: int = int(os.getenv("DASHSCOPE_ASR_SAMPLE_RATE", "16000"))
    disfluency_removal_enabled: bool = (
        os.getenv("DASHSCOPE_ASR_DISFLUENCY_REMOVAL", "false").lower() == "true"
    )

    def validate(self) -> None:
        if not self.api_key:
            raise RuntimeError("Missing required environment variable: DASHSCOPE_API_KEY")


@dataclass(frozen=True)
class FsmnVadConfig:
    model: str = os.getenv(
        "FSMN_VAD_MODEL",
        "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    )
    device: str = os.getenv("FSMN_VAD_DEVICE", "cpu")
    sample_rate: int = int(os.getenv("FSMN_VAD_SAMPLE_RATE", "16000"))
    chunk_size_ms: int = int(os.getenv("FSMN_VAD_CHUNK_SIZE_MS", "200"))
    max_end_silence_time_ms: int = int(
        os.getenv("FSMN_VAD_MAX_END_SILENCE_TIME_MS", "800")
    )
    ncpu: int = int(os.getenv("FSMN_VAD_NCPU", "4"))


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig = ServerConfig()
    audio: AudioConfig = AudioConfig()
    dashscope_asr: DashScopeAsrConfig = DashScopeAsrConfig()
    fsmn_vad: FsmnVadConfig = FsmnVadConfig()

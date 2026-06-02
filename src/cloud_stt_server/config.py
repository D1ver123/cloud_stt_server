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
class DoubaoAsrConfig:
    endpoint: str = os.getenv(
        "DOUBAO_ASR_ENDPOINT",
        "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
    )
    api_key: str | None = "76079355-24e4-45ef-a449-b171d53faa36"
    app_key: str | None = None
    access_key: str | None = None
    resource_id: str = os.getenv(
        "DOUBAO_ASR_RESOURCE_ID",
        "volc.seedasr.sauc.duration",
    )
    model_name: str = os.getenv("DOUBAO_ASR_MODEL_NAME", "bigmodel")
    format: str = os.getenv("DOUBAO_ASR_FORMAT", "pcm")
    sample_rate: int = int(os.getenv("DOUBAO_ASR_SAMPLE_RATE", "16000"))
    bits: int = int(os.getenv("DOUBAO_ASR_BITS", "16"))
    channels: int = int(os.getenv("DOUBAO_ASR_CHANNELS", "1"))
    codec: str = os.getenv("DOUBAO_ASR_CODEC", "raw")
    packet_duration_ms: int = int(os.getenv("DOUBAO_ASR_PACKET_DURATION_MS", "200"))
    language: str | None = os.getenv("DOUBAO_ASR_LANGUAGE")
    uid: str = os.getenv("DOUBAO_ASR_UID", "cloud-stt")
    enable_itn: bool = os.getenv("DOUBAO_ASR_ENABLE_ITN", "true").lower() == "true"
    enable_punc: bool = os.getenv("DOUBAO_ASR_ENABLE_PUNC", "true").lower() == "true"
    enable_ddc: bool = os.getenv("DOUBAO_ASR_ENABLE_DDC", "false").lower() == "true"
    enable_nonstream: bool = (
        os.getenv("DOUBAO_ASR_ENABLE_NONSTREAM", "true").lower() == "true"
    )
    show_utterances: bool = (
        os.getenv("DOUBAO_ASR_SHOW_UTTERANCES", "true").lower() == "true"
    )
    end_window_size: int = int(os.getenv("DOUBAO_ASR_END_WINDOW_SIZE", "800"))

    def validate(self) -> None:
        if self.api_key:
            return
        if self.app_key and self.access_key:
            return
        raise RuntimeError(
            "Missing Doubao ASR credentials: set DOUBAO_ASR_API_KEY, "
            "or set both DOUBAO_ASR_APP_KEY and DOUBAO_ASR_ACCESS_KEY"
        )

    def build_headers(self, request_id: str) -> dict[str, str]:
        headers = {
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Connect-Id": request_id,
            "X-Api-Sequence": "-1",
        }
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        else:
            headers["X-Api-App-Key"] = str(self.app_key)
            headers["X-Api-Access-Key"] = str(self.access_key)
        return headers


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
    doubao_asr: DoubaoAsrConfig = DoubaoAsrConfig()
    fsmn_vad: FsmnVadConfig = FsmnVadConfig()

from cloud_stt_client.encoding import setup_opus
from cloud_stt_server.audio.pcm import validate_pcm_s16le


class AudioDecoder:
    def __init__(
        self,
        audio_format: str,
        sample_rate: int,
        channels: int,
        frame_duration_ms: int,
        opus_lib_path: str | None = None,
    ):
        self.audio_format = audio_format
        self._opus_decoder = None
        if audio_format == "opus":
            setup_opus(opus_lib_path)
            try:
                import opuslib
            except ImportError as exc:
                raise RuntimeError("Opus support requires opuslib.") from exc
            self._opuslib = opuslib
            self._frame_size = sample_rate * frame_duration_ms // 1000
            self._opus_decoder = opuslib.Decoder(sample_rate, channels)

    def decode(self, data: bytes) -> bytes:
        if self.audio_format == "pcm_s16le":
            validate_pcm_s16le(data)
            return data
        if self.audio_format == "opus":
            if self._opus_decoder is None:
                raise ValueError("opus decoder is not initialized")
            try:
                pcm = self._opus_decoder.decode(data, self._frame_size)
            except self._opuslib.OpusError as exc:
                raise ValueError(f"opus decode failed: {exc}") from exc
            validate_pcm_s16le(pcm)
            return pcm
        raise ValueError(f"unsupported audio format: {self.audio_format}")


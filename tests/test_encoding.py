import pytest

from cloud_stt_client.config import AudioConfig
from cloud_stt_client.encoding import PcmPassthroughEncoder, _candidate_paths, create_encoder
from cloud_stt_server.audio.decoder import AudioDecoder


def test_audio_config_defaults_to_opus():
    assert AudioConfig().format == "opus"


def test_pcm_encoder_is_still_available_for_fallback():
    encoder = create_encoder(AudioConfig(format="pcm_s16le"))

    assert isinstance(encoder, PcmPassthroughEncoder)
    assert encoder.encode(b"\x00\x00") == b"\x00\x00"


def test_opus_candidates_only_include_existing_paths():
    candidates = _candidate_paths(None)

    assert all(path.exists() for path in candidates)


def test_opus_encoder_decoder_roundtrip_when_libopus_available():
    config = AudioConfig(format="opus")
    pcm = b"\x00\x00" * config.frame_samples

    try:
        encoder = create_encoder(config)
        decoder = AudioDecoder(
            audio_format="opus",
            sample_rate=config.sample_rate,
            channels=config.channels,
            frame_duration_ms=config.frame_duration_ms,
        )
    except RuntimeError as exc:
        pytest.skip(str(exc))

    packet = encoder.encode(pcm)
    decoded = decoder.decode(packet)

    assert packet
    assert len(decoded) == len(pcm)

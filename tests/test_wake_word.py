import sys
from types import SimpleNamespace

from cloud_stt_client.audio.wake_word import WakeWordDetector
from cloud_stt_client.config import WakeWordConfig


class FakeStream:
    def __init__(self):
        self.ready = False
        self.waveform = None

    def accept_waveform(self, sample_rate, waveform):
        self.sample_rate = sample_rate
        self.waveform = waveform
        self.ready = True


class FakeKeywordSpotter:
    kwargs = None

    def __init__(self, **kwargs):
        FakeKeywordSpotter.kwargs = kwargs
        self.decoded = False

    def create_stream(self):
        self.stream = FakeStream()
        return self.stream

    def is_ready(self, stream):
        return stream.ready and not self.decoded

    def decode_stream(self, stream):
        self.decoded = True

    def get_result(self, stream):
        return "hello"

    def reset_stream(self, stream):
        stream.ready = False
        self.decoded = False


def test_wake_word_detector_processes_pcm_with_sherpa_keyword_spotter(
    monkeypatch,
    tmp_path,
):
    for name in ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "keywords.txt"):
        (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "sherpa_onnx",
        SimpleNamespace(KeywordSpotter=FakeKeywordSpotter),
    )

    detector = WakeWordDetector(
        WakeWordConfig(enabled=True, model_dir=str(tmp_path), keywords_score=1.7),
        sample_rate=16000,
    )

    detection = detector.process_pcm(b"\x00\x00" * 320)

    assert detection is not None
    assert detection.text == "hello"
    assert FakeKeywordSpotter.kwargs["sample_rate"] == 16000
    assert FakeKeywordSpotter.kwargs["keywords_score"] == 1.7
    assert FakeKeywordSpotter.kwargs["keywords_file"].endswith("keywords.txt")

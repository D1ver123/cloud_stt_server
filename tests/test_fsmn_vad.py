from cloud_stt_server.config import FsmnVadConfig
from cloud_stt_server.vad.fsmn_vad import FsmnVadTracker


class FakeVadModel:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def generate(self, **kwargs):
        if not self.outputs:
            return [{"key": "utt", "value": []}]
        return [{"key": "utt", "value": self.outputs.pop(0)}]


def test_fsmn_vad_tracker_detects_start_and_end():
    model = FakeVadModel(
        [
            [],
            [[120, -1]],
            [],
            [[-1, 960]],
            [],
        ]
    )
    config = FsmnVadConfig(model="fake", chunk_size_ms=200)
    tracker = FsmnVadTracker(config, model_factory=lambda _: model)
    frame = b"\x00\x00" * 320

    assert tracker.observe(frame).speech_start is False

    start = tracker.observe(frame)
    assert start.speech_start is True
    assert start.speech_end is False
    assert start.start_time_ms == 120

    middle = tracker.observe(frame)
    assert middle.speech_start is True
    assert middle.speech_end is False

    end = tracker.observe(frame)
    assert end.speech_start is True
    assert end.speech_end is True
    assert end.end_time_ms == 960

    assert tracker.observe(frame).speech_start is False

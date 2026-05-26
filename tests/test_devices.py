from types import SimpleNamespace

from cloud_stt_client.audio import devices


class FakeSoundDevice:
    def __init__(self):
        self.default = SimpleNamespace(device=(1, None))
        self._devices = [
            {
                "name": "External Mic",
                "max_input_channels": 1,
                "default_samplerate": 48000,
                "hostapi": 0,
            },
            {
                "name": "System Default Mic",
                "max_input_channels": 2,
                "default_samplerate": 44100,
                "hostapi": 1,
            },
            {
                "name": "USB Conference Mic",
                "max_input_channels": 1,
                "default_samplerate": 16000,
                "hostapi": 1,
            },
        ]

    def query_devices(self, device=None):
        if device is None:
            return self._devices
        return self._devices[device]

    def query_hostapis(self):
        return [{"name": "MME"}, {"name": "Windows WASAPI"}]


def test_select_input_device_uses_system_default(monkeypatch, tmp_path):
    fake_sd = FakeSoundDevice()
    monkeypatch.setattr(devices, "_import_sounddevice", lambda: fake_sd)
    monkeypatch.setenv("CLOUD_STT_CLIENT_PREFS", str(tmp_path / "prefs.json"))

    selected = devices.select_input_device()

    assert selected.index == 1
    assert selected.name == "System Default Mic"


def test_explicit_input_device_is_remembered(monkeypatch, tmp_path):
    fake_sd = FakeSoundDevice()
    prefs = tmp_path / "prefs.json"
    monkeypatch.setattr(devices, "_import_sounddevice", lambda: fake_sd)
    monkeypatch.setenv("CLOUD_STT_CLIENT_PREFS", str(prefs))

    selected = devices.select_input_device(2, remember_explicit=True)

    assert selected.index == 2
    assert "USB Conference Mic" in prefs.read_text(encoding="utf-8")


def test_remembered_input_device_overrides_system_default(monkeypatch, tmp_path):
    fake_sd = FakeSoundDevice()
    prefs = tmp_path / "prefs.json"
    monkeypatch.setattr(devices, "_import_sounddevice", lambda: fake_sd)
    monkeypatch.setenv("CLOUD_STT_CLIENT_PREFS", str(prefs))
    devices.select_input_device(2, remember_explicit=True)

    selected = devices.select_input_device()

    assert selected.index == 2
    assert selected.name == "USB Conference Mic"

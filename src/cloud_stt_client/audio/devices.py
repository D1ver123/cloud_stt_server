from dataclasses import dataclass
import platform
import re
from typing import Any

from cloud_stt_client.preferences import load_preferences, save_preferences


_VIRTUAL_PATTERNS = [
    r"blackhole",
    r"aggregate",
    r"multi[-\s]?output",
    r"monitor",
    r"echo[-\s]?cancel",
    r"vb[-\s]?cable",
    r"voicemeeter",
    r"cable (input|output)",
    r"loopback",
]


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    sample_rate: int
    channels: int
    hostapi: str | None = None


def _import_sounddevice():
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            "sounddevice is required for microphone capture. "
            "Install with: pip install -e .[audio]"
        ) from exc
    return sd


def _is_virtual(name: str) -> bool:
    normalized = name.casefold()
    return any(re.search(pattern, normalized) for pattern in _VIRTUAL_PATTERNS)


def _hostapi_names(sd: Any) -> dict[int, str]:
    try:
        hostapis = list(sd.query_hostapis())
    except Exception:
        return {}
    return {index: str(value.get("name", "")) for index, value in enumerate(hostapis)}


def list_input_devices(include_virtual: bool = False) -> list[AudioDevice]:
    sd = _import_sounddevice()
    hostapis = _hostapi_names(sd)
    devices: list[AudioDevice] = []
    for index, raw in enumerate(sd.query_devices()):
        channels = int(raw.get("max_input_channels", 0))
        if channels <= 0:
            continue
        name = str(raw.get("name", "Unknown"))
        if not include_virtual and _is_virtual(name):
            continue
        sample_rate = int(raw.get("default_samplerate") or 16000)
        hostapi = hostapis.get(int(raw.get("hostapi", -1)))
        devices.append(
            AudioDevice(
                index=index,
                name=name,
                sample_rate=sample_rate,
                channels=channels,
                hostapi=hostapi,
            )
        )
    return devices


def select_input_device(
    device_id: int | None = None,
    include_virtual: bool = False,
    remember_explicit: bool = False,
) -> AudioDevice:
    sd = _import_sounddevice()
    devices = list_input_devices(include_virtual=include_virtual)
    if not devices:
        raise RuntimeError("No input audio device is available.")

    if device_id is not None:
        for device in devices:
            if device.index == device_id:
                if remember_explicit:
                    save_preferred_input_device(device)
                return device
        raise ValueError(f"Input device not found: {device_id}")

    preferred = _select_preferred_input_device(devices)
    if preferred is not None:
        return preferred

    default = _select_default_input_device(sd, include_virtual=include_virtual)
    if default is not None:
        return default

    return _select_by_hostapi_priority(devices)


def save_preferred_input_device(device: AudioDevice) -> None:
    preferences = load_preferences()
    preferences["input_device"] = {
        "index": device.index,
        "name": device.name,
        "hostapi": device.hostapi,
    }
    save_preferences(preferences)


def _select_preferred_input_device(devices: list[AudioDevice]) -> AudioDevice | None:
    preference = load_preferences().get("input_device")
    if not isinstance(preference, dict):
        return None

    preferred_index = preference.get("index")
    if isinstance(preferred_index, int):
        for device in devices:
            if device.index == preferred_index:
                return device

    preferred_name = str(preference.get("name", ""))
    preferred_hostapi = str(preference.get("hostapi", ""))
    if preferred_name:
        for device in devices:
            if device.name == preferred_name and str(device.hostapi or "") == preferred_hostapi:
                return device

    return None


def _select_default_input_device(
    sd: Any,
    include_virtual: bool = False,
) -> AudioDevice | None:
    device_id = _default_input_device_id(sd)
    if device_id is None:
        return None

    hostapis = _hostapi_names(sd)
    try:
        raw = sd.query_devices(device_id)
    except Exception:
        return None

    channels = int(raw.get("max_input_channels", 0))
    if channels <= 0:
        return None

    name = str(raw.get("name", "Unknown"))
    if not include_virtual and _is_virtual(name):
        return None

    return AudioDevice(
        index=device_id,
        name=name,
        sample_rate=int(raw.get("default_samplerate") or 16000),
        channels=channels,
        hostapi=hostapis.get(int(raw.get("hostapi", -1))),
    )


def _default_input_device_id(sd: Any) -> int | None:
    default_device = getattr(sd, "default", None)
    if default_device is None:
        return None

    value = getattr(default_device, "device", None)
    if value is None:
        return None

    if isinstance(value, (list, tuple)):
        value = value[0] if value else None

    try:
        device_id = int(value)
    except (TypeError, ValueError):
        return None

    if device_id < 0:
        return None
    return device_id


def _select_by_hostapi_priority(devices: list[AudioDevice]) -> AudioDevice:
    system = platform.system().lower()
    host_order = {
        "windows": ["wasapi", "wdm-ks", "directsound", "mme"],
        "darwin": ["core audio"],
    }.get(system, ["alsa", "jack", "oss", "pulse", "pipewire"])

    for token in host_order:
        for device in devices:
            hostapi = (device.hostapi or "").casefold()
            if token in hostapi:
                return device

    return devices[0]

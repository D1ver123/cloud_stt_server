import json
import os
from pathlib import Path
from typing import Any


APP_NAME = "xiaozhi-cloud-stt"
PREFERENCES_FILE = "client_preferences.json"


def preferences_path() -> Path:
    override = os.getenv("CLOUD_STT_CLIENT_PREFS")
    if override:
        return Path(override)

    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME / PREFERENCES_FILE

    return Path.home() / ".config" / APP_NAME / PREFERENCES_FILE


def load_preferences(path: Path | None = None) -> dict[str, Any]:
    target = path or preferences_path()
    if not target.exists():
        return {}
    try:
        with target.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_preferences(preferences: dict[str, Any], path: Path | None = None) -> None:
    target = path or preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file:
        json.dump(preferences, file, ensure_ascii=False, indent=2)
        file.write("\n")

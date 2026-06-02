from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any


class ConversationRecognitionLog:
    """Collect final STT results and write one client-side log at stream close."""

    def __init__(
        self,
        directory: str | Path,
        session_id: str,
        enabled: bool = True,
        write_empty: bool = False,
    ):
        self.directory = Path(directory)
        self.session_id = session_id
        self.enabled = enabled
        self.write_empty = write_empty
        self.started_at = _now_iso()
        self.results: list[dict[str, Any]] = []
        self._written_path: Path | None = None

    def record_final(self, event: dict) -> None:
        self.results.append(
            {
                "index": len(self.results) + 1,
                "received_at": _now_iso(),
                "text": str(event.get("text", "")),
                "event": dict(event),
            }
        )

    def write(self) -> Path | None:
        if not self.enabled or self._written_path is not None:
            return self._written_path
        if not self.results and not self.write_empty:
            return None

        ended_at = _now_iso()
        payload = {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": ended_at,
            "result_count": len(self.results),
            "results": self.results,
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / self._filename(ended_at)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._written_path = path
        return path

    def _filename(self, ended_at: str) -> str:
        timestamp = ended_at.replace("-", "").replace(":", "").replace("+", "_")
        timestamp = re.sub(r"[^0-9A-Za-z_.-]+", "_", timestamp)
        session_id = re.sub(r"[^0-9A-Za-z_.-]+", "_", self.session_id)
        return f"recognition_{timestamp}_{session_id}.json"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

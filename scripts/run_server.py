from pathlib import Path
import os
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
LOG = ROOT / "server.startup.log"

sys.path.insert(0, str(SRC))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

try:
    import uvicorn
    from cloud_stt_server.app import app

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
except Exception as exc:
    LOG.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
    raise

"""Isolated loopback-only backend for browser tests, with provider calls disabled."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.update(LLM_API_KEY="", LLM_BASE_URL="", LLM_MODEL="", STATIC_DIR=str(ROOT / "frontend/dist"))

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="yanzheng-browser-") as directory:
        os.environ["DATA_DIR"] = directory
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=18083)

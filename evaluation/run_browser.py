"""Run isolated headless browser checks with a local Chrome/Edge or Playwright Chromium."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = os.environ.copy()
    env.pop("NO_COLOR", None)
    env.pop("FORCE_COLOR", None)
    env.update(LLM_API_KEY="", LLM_BASE_URL="", LLM_MODEL="", PYTHONIOENCODING="utf-8")
    if os.name == "nt" and not env.get("YANZHENG_TEST_BROWSER"):
        candidates = [Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
                      Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
                      Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"]
        for candidate in candidates:
            if candidate.is_file():
                env["YANZHENG_TEST_BROWSER"] = str(candidate)
                break
    result = subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "run", "test:e2e"], cwd=ROOT / "frontend", env=env)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

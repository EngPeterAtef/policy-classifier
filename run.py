#!/usr/bin/env python3
"""One command to run everything.

    python3 run.py                  set up, build the page, start the app on http://localhost:8000
    python3 run.py eval             run the classifier over cases.yaml and write RESULTS.md
    python3 run.py eval --limit 5   a smoke test of the first 5 cases
    python3 run.py test             run the unit tests (no key and no network needed)

The first run creates .venv, installs the Python packages, and builds the React page
(needs Node 18 or newer). Later runs skip whatever is already up to date.

This file uses only the Python standard library, so it runs before anything is installed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
WEB = ROOT / "web"
DIST = WEB / "dist"


def say(message: str) -> None:
    print(f"[run.py] {message}", flush=True)


def fail(message: str) -> None:
    print(f"[run.py] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_python_env() -> None:
    if sys.version_info < (3, 10):
        fail(f"Python 3.10 or newer is needed. This is {sys.version.split()[0]}.")
    if not venv_python().exists():
        say("creating .venv")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    requirements = ROOT / "requirements.txt"
    stamp = VENV / ".requirements-hash"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not stamp.exists() or stamp.read_text().strip() != digest:
        say("installing Python packages")
        subprocess.run(
            [str(venv_python()), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(requirements)],
            check=True,
        )
        stamp.write_text(digest)


def ensure_page() -> None:
    index = DIST / "index.html"
    sources = [WEB / "index.html", WEB / "package.json", WEB / "vite.config.js", *(WEB / "src").rglob("*")]
    if index.exists() and not any(p.is_file() and p.stat().st_mtime > index.stat().st_mtime for p in sources):
        return
    npm = shutil.which("npm")
    if not npm:
        fail("Node.js is needed to build the page (Node 18 or newer, with npm). Install it and run again.")
    if not (WEB / "node_modules").exists():
        say("installing web packages")
        install = "ci" if (WEB / "package-lock.json").exists() else "install"
        subprocess.run([npm, install, "--no-audit", "--no-fund"], cwd=WEB, check=True)
    say("building the page")
    subprocess.run([npm, "run", "build"], cwd=WEB, check=True)


def run_python(args: list[str]) -> int:
    return subprocess.run([str(venv_python()), *args], cwd=ROOT).returncode


def main(argv: list[str]) -> int:
    if argv[:1] and argv[0] in ("help", "-h", "--help"):
        print(__doc__)
        return 0
    command, rest = (argv[0], argv[1:]) if argv and not argv[0].startswith("-") else ("app", argv)
    ensure_python_env()
    if command == "eval":
        return run_python(["evaluate.py", *rest])
    if command == "test":
        return run_python(["-m", "pytest", *rest])
    if command != "app":
        fail(f"unknown command {command!r}. Try: python3 run.py help")
    port = rest[rest.index("--port") + 1] if "--port" in rest else "8000"
    ensure_page()
    if not (ROOT / ".env").exists():
        say("no .env found: the page will open, but classifying needs a key. Copy .env.example to .env.")
    say(f"starting the app: http://localhost:{port}   (Ctrl+C to stop)")
    try:
        return run_python(["-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", port])
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

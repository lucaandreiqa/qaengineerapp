#!/bin/bash
# One-time setup on macOS: virtualenv, Python packages, Playwright browser.
# Double-click in Finder, or run ./setup.command in Terminal.
set -e
cd "$(dirname "$0")"

# Pick a Python 3.10+ (Pillow and the pinned packages need it; macOS's own python3 can be 3.9).
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is needed."
  echo "Install it with Homebrew (brew install python@3.12) or from https://www.python.org/downloads/macos/"
  read -r -p "Press Return to close..." _ || true
  exit 1
fi
echo "Using $($PY --version) at $(command -v $PY)"

[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium

chmod +x ./*.command 2>/dev/null || true
echo
echo "Setup complete. Start the app with run_app.command"
command -v npx >/dev/null 2>&1 || echo "Optional: install Node.js (brew install node) for Lighthouse and ticket specs."
read -r -p "Press Return to close..." _ || true

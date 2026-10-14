#!/bin/bash
# Start the web UI at http://127.0.0.1:8765 and open it in your browser. Close this window (or Ctrl+C) to stop.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then echo "Run setup.command first."; read -r -p "Press Return to close..." _; exit 1; fi
exec .venv/bin/python -m qa_app "$@"

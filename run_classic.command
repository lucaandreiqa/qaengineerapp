#!/bin/bash
# The original PySide6 desktop window.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then echo "Run setup.command first."; read -r -p "Press Return to close..." _; exit 1; fi
exec .venv/bin/python -m qa_app --classic "$@"

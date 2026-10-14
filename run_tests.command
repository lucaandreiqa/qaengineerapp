#!/bin/bash
# Workflow tests (pytest).
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then echo "Run setup.command first."; read -r -p "Press Return to close..." _; exit 1; fi
.venv/bin/python -m pip install -q -r requirements-dev.txt
.venv/bin/python -m pytest -q
status=$?
[ -t 0 ] && read -r -p "Press Return to close..." _ || true
exit $status

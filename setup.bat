@echo off
REM One-time setup: virtualenv, Python packages, Playwright browser.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
echo.
echo Setup complete. Start the app with run_app.bat
pause

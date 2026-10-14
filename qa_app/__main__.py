"""Launch the app:

    python -m qa_app              web UI in your browser: Board, Run, History, Integrations
    python -m qa_app --classic    the original desktop window (PySide6)
    python -m qa_app --port 9000 --no-browser
"""
import argparse
import socket
import sys
import threading
import webbrowser

from .config import APP_DIR, ensure_dirs


def classic() -> int:
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("QA Engineer App")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


def web(host: str, port: int, open_browser: bool) -> int:
    import uvicorn

    url = f"http://{host}:{port}/"
    with socket.socket() as s:
        if s.connect_ex((host, port)) == 0:  # already running: just show it
            if open_browser:
                webbrowser.open(url)
            return 0
    if sys.stdout is None or sys.stderr is None:  # started with pythonw (run_app.bat): log to a file
        log = open(APP_DIR / "web.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"QA Engineer App running at {url}  (Ctrl+C to stop)")
    from .web import server as web_server

    # timeout_graceful_shutdown: never wait more than 3 s for open connections after Ctrl+C.
    server = uvicorn.Server(uvicorn.Config(web_server.app, host=host, port=port, log_level="warning",
                                           timeout_graceful_shutdown=3))
    web_server._server = server  # lets the live-update stream end itself on Ctrl+C
    try:
        server.run()
    except KeyboardInterrupt:  # uvicorn re-raises Ctrl+C after a clean shutdown
        pass
    print("QA Engineer App stopped.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="qa_app")
    ap.add_argument("--classic", action="store_true", help="open the original PySide6 window")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    ensure_dirs()
    return classic() if args.classic else web(args.host, args.port, not args.no_browser)


if __name__ == "__main__":
    sys.exit(main())

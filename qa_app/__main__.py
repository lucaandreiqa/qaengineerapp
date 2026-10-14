"""Launch the desktop app:  python -m qa_app"""
import sys

from PySide6.QtWidgets import QApplication

from .config import ensure_dirs
from .ui.main_window import MainWindow


def main() -> int:
    ensure_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName("QA Engineer App")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

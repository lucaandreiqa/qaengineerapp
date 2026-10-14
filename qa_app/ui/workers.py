"""Background threads so the UI stays responsive while Playwright and integrations run."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .. import integrations
from ..config import load_settings
from ..models import RunConfig, RunResult
from ..runner import Runner


class RunWorker(QThread):
    log = Signal(str)
    finding = Signal(object)
    progress = Signal(int, int)
    finished_run = Signal(object)
    failed = Signal(str)

    def __init__(self, config: RunConfig, publish: bool):
        super().__init__()
        self.publish = publish
        self.runner = Runner(config, log=self.log.emit, on_finding=self.finding.emit,
                             on_progress=self.progress.emit)

    def cancel(self) -> None:
        self.runner.cancel()

    def run(self) -> None:
        try:
            result = self.runner.run()
            if self.publish and not self.runner.cancelled.is_set():
                self.log.emit("Publishing to integrations…")
                integrations.publish(result, load_settings(), log=self.log.emit)
            self.finished_run.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class PublishWorker(QThread):
    log = Signal(str)
    done = Signal(dict)

    def __init__(self, result: RunResult):
        super().__init__()
        self.result = result

    def run(self) -> None:
        self.done.emit(integrations.publish(self.result, load_settings(), log=self.log.emit))


class TestConnectionWorker(QThread):
    done = Signal(str, bool)

    def __init__(self, name: str, cfg: dict):
        super().__init__()
        self.name, self.cfg = name, cfg

    def run(self) -> None:
        try:
            self.done.emit(integrations.test_connection(self.name, self.cfg), True)
        except Exception as e:
            self.done.emit(str(e).splitlines()[0][:300], False)

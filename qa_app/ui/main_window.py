"""Main desktop window: Run · History · Integrations."""
from __future__ import annotations

import json
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..checks import VIEWPORTS, lighthouse
from ..config import DEFAULT_SETTINGS, RUNS_DIR, SECRET_KEYS, load_settings, save_settings
from ..models import Finding, PageResult, RunConfig, RunResult, Severity
from .workers import PublishWorker, RunWorker, TestConnectionWorker

SEV_COLORS = {"critical": "#c62828", "major": "#ef6c00", "minor": "#b58900", "info": "#607d8b"}
CHECKS = [("functional", "Functional (crawl, JS errors, broken links)"),
          ("visual", "Visual regression"),
          ("accessibility", "Accessibility (axe-core WCAG)"),
          ("seo", "SEO"),
          ("performance", "Performance (timing + Lighthouse)")]
INTEGRATION_TITLES = {"slack": "Slack", "teams": "Microsoft Teams", "jira": "Jira",
                      "testrail": "TestRail", "xray": "Xray (Jira)", "zephyr": "Zephyr Scale", "aws": "AWS S3"}


class SeverityItem(QTableWidgetItem):
    """Sorts by severity rank instead of alphabetically."""
    def __lt__(self, other: QTableWidgetItem) -> bool:
        return (self.data(Qt.UserRole + 1) or 0) < (other.data(Qt.UserRole + 1) or 0)


def result_from_json(path: Path) -> RunResult:
    d = json.loads(path.read_text(encoding="utf-8"))
    cfg = RunConfig(**d["config"])
    r = RunResult(d["run_id"], cfg, datetime.fromisoformat(d["started"]),
                  datetime.fromisoformat(d["finished"]) if d.get("finished") else None,
                  [PageResult(**p) for p in d["pages"]],
                  [Finding(**{**f, "severity": Severity(f["severity"])}) for f in d["findings"]],
                  d.get("metrics", {}), str(path.parent), d.get("report_path", ""))
    return r


class RunTab(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window = window
        self.worker: RunWorker | None = None
        self.result: RunResult | None = None
        self.findings: list[Finding] = []

        self.url = QLineEdit(placeholderText="https://your-site.com")
        self.url.returnPressed.connect(self.start)
        self.check_boxes = {k: QCheckBox(label, checked=k != "performance") for k, label in CHECKS}
        self.viewport_boxes = {k: QCheckBox(k, checked=k in ("desktop", "mobile")) for k in VIEWPORTS}
        self.max_pages = QSpinBox(minimum=1, maximum=500, value=10)
        self.threshold = QDoubleSpinBox(minimum=0, maximum=100, value=0.5, singleStep=0.1, suffix=" %")
        self.lighthouse = QCheckBox("Use Lighthouse", checked=lighthouse.available())
        self.update_baselines = QCheckBox("Accept current screenshots as new baselines")
        self.headed = QCheckBox("Show browser window")
        self.publish = QCheckBox("Publish results to enabled integrations")

        self.run_btn = QPushButton("▶  Run tests")
        self.run_btn.setStyleSheet("font-weight:600;padding:8px 18px")
        self.run_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Stop", enabled=False)
        self.stop_btn.clicked.connect(self.stop)
        self.report_btn = QPushButton("Open HTML report", enabled=False)
        self.report_btn.clicked.connect(lambda: self.result and webbrowser.open(Path(self.result.report_path).as_uri()))
        self.progress = QProgressBar(textVisible=True)
        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight:600")

        # left: configuration
        checks_box = QGroupBox("Checks")
        cl = QVBoxLayout(checks_box)
        for cb in self.check_boxes.values():
            cl.addWidget(cb)
        opts = QGroupBox("Options")
        form = QFormLayout(opts)
        vp_row = QHBoxLayout()
        for cb in self.viewport_boxes.values():
            vp_row.addWidget(cb)
        form.addRow("Max pages", self.max_pages)
        form.addRow("Viewports", vp_row)
        form.addRow("Visual diff threshold", self.threshold)
        for w in (self.lighthouse, self.update_baselines, self.headed, self.publish):
            form.addRow(w)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Website URL"))
        ll.addWidget(self.url)
        ll.addWidget(checks_box)
        ll.addWidget(opts)
        btns = QHBoxLayout()
        btns.addWidget(self.run_btn)
        btns.addWidget(self.stop_btn)
        ll.addLayout(btns)
        ll.addWidget(self.progress)
        ll.addStretch()
        left.setMaximumWidth(420)

        # right: results
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Severity", "Check", "Finding", "Page"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.detail = QPlainTextEdit(readOnly=True)
        self.shot = QLabel(alignment=Qt.AlignCenter)
        self.shot.setMinimumHeight(160)
        self.shot.mousePressEvent = lambda e: self._open_shot()
        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setMaximumBlockCount(5000)

        detail_split = QSplitter(Qt.Horizontal)
        detail_split.addWidget(self.detail)
        detail_split.addWidget(self.shot)
        tabs = QTabWidget()
        tabs.addTab(detail_split, "Details")
        tabs.addTab(self.log_view, "Log")
        self.bottom_tabs = tabs
        right_split = QSplitter(Qt.Vertical)
        right_split.addWidget(self.table)
        right_split.addWidget(tabs)
        right_split.setSizes([450, 250])
        right = QWidget()
        rl = QVBoxLayout(right)
        top = QHBoxLayout()
        top.addWidget(self.summary, 1)
        top.addWidget(self.report_btn)
        rl.addLayout(top)
        rl.addWidget(right_split)

        layout = QHBoxLayout(self)
        layout.addWidget(left)
        layout.addWidget(right, 1)

    # ---- run lifecycle
    def start(self) -> None:
        url = self.url.text().strip()
        checks = [k for k, cb in self.check_boxes.items() if cb.isChecked()]
        if not url or not checks:
            QMessageBox.warning(self, "QA App", "Enter a URL and select at least one check.")
            return
        cfg = RunConfig(url=url, checks=checks, max_pages=self.max_pages.value(),
                        viewports=[k for k, cb in self.viewport_boxes.items() if cb.isChecked()] or ["desktop"],
                        visual_threshold=self.threshold.value(), use_lighthouse=self.lighthouse.isChecked(),
                        headless=not self.headed.isChecked(), update_baselines=self.update_baselines.isChecked())
        self.table.setRowCount(0)
        self.findings.clear()
        self.log_view.clear()
        self.detail.clear()
        self.shot.clear()
        self.summary.setText("Running…")
        self.report_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.bottom_tabs.setCurrentIndex(1)

        self.worker = RunWorker(cfg, self.publish.isChecked())
        self.worker.log.connect(self.log_view.appendPlainText)
        self.worker.finding.connect(self.add_finding)
        self.worker.progress.connect(lambda d, t: (self.progress.setMaximum(t), self.progress.setValue(d)))
        self.worker.finished_run.connect(self.done)
        self.worker.failed.connect(self.failed)
        self.worker.start()

    def stop(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.stop_btn.setEnabled(False)
            self.log_view.appendPlainText("Stopping after current step…")

    def done(self, result: RunResult) -> None:
        self.result = result
        color = "#2e7d32" if result.passed else "#c62828"
        self.summary.setText(f"<span style='color:{color}'>{result.summary_line()}</span>")
        self.report_btn.setEnabled(True)
        self._reset_buttons()
        self.window.history.refresh()

    def failed(self, message: str) -> None:
        self.summary.setText(f"<span style='color:#c62828'>Run failed: {message}</span>")
        self.log_view.appendPlainText(f"ERROR: {message}")
        self._reset_buttons()

    def _reset_buttons(self) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ---- findings
    def add_finding(self, f: Finding) -> None:
        self.findings.append(f)
        self.table.setSortingEnabled(False)
        row = self.table.rowCount()
        self.table.insertRow(row)
        sev = SeverityItem(f.severity.value)
        sev.setForeground(QColor(SEV_COLORS[f.severity.value]))
        sev.setData(Qt.UserRole, len(self.findings) - 1)
        sev.setData(Qt.UserRole + 1, f.severity.rank)
        for col, item in enumerate([sev, QTableWidgetItem(f.check), QTableWidgetItem(f.title), QTableWidgetItem(f.url)]):
            self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)

    def show_detail(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        f = self.findings[self.table.item(rows[0].row(), 0).data(Qt.UserRole)]
        self.bottom_tabs.setCurrentIndex(0)
        self.detail.setPlainText(f"{f.title}\n\nSeverity: {f.severity.value}\nCheck: {f.check}\n"
                                 f"Page: {f.url}\n\n{f.details}")
        self._current_shot = f.screenshot
        if f.screenshot and Path(f.screenshot).exists():
            pix = QPixmap(f.screenshot)
            self.shot.setPixmap(pix.scaled(self.shot.width(), max(self.shot.height(), 160),
                                           Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.shot.setToolTip("Click to open full size")
        else:
            self.shot.clear()
            self.shot.setText("No screenshot")

    def _open_shot(self) -> None:
        if getattr(self, "_current_shot", None):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_shot))


class HistoryTab(QWidget):
    def __init__(self):
        super().__init__()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Run", "URL", "Status", "Critical", "Major", "Minor"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.open_report)
        self.log = QPlainTextEdit(readOnly=True, maximumHeight=140)
        open_btn = QPushButton("Open report")
        open_btn.clicked.connect(self.open_report)
        folder_btn = QPushButton("Open folder")
        folder_btn.clicked.connect(self.open_folder)
        publish_btn = QPushButton("Publish to integrations")
        publish_btn.clicked.connect(self.publish)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        bar = QHBoxLayout()
        for b in (open_btn, folder_btn, publish_btn):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(refresh_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.table)
        layout.addWidget(self.log)
        self.paths: list[Path] = []
        self.refresh()

    def refresh(self) -> None:
        self.paths = sorted(RUNS_DIR.glob("*/result.json"), reverse=True) if RUNS_DIR.exists() else []
        self.table.setRowCount(0)
        for path in self.paths:
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            counts = {s: sum(1 for f in d["findings"] if f["severity"] == s) for s in ("critical", "major", "minor")}
            row = self.table.rowCount()
            self.table.insertRow(row)
            status = QTableWidgetItem("PASSED" if d["passed"] else "FAILED")
            status.setForeground(QColor("#2e7d32" if d["passed"] else "#c62828"))
            for col, item in enumerate([QTableWidgetItem(d["run_id"]), QTableWidgetItem(d["config"]["url"]), status,
                                        QTableWidgetItem(str(counts["critical"])), QTableWidgetItem(str(counts["major"])),
                                        QTableWidgetItem(str(counts["minor"]))]):
                self.table.setItem(row, col, item)

    def _selected(self) -> Path | None:
        rows = self.table.selectionModel().selectedRows()
        return self.paths[rows[0].row()] if rows else None

    def open_report(self) -> None:
        if p := self._selected():
            webbrowser.open((p.parent / "report.html").as_uri())

    def open_folder(self) -> None:
        if p := self._selected():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))

    def publish(self) -> None:
        if not (p := self._selected()):
            return
        self.log.clear()
        self.worker = PublishWorker(result_from_json(p))
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.done.connect(lambda out: self.log.appendPlainText(
            "Done." if out else "No integrations enabled — configure them in the Integrations tab."))
        self.worker.start()


class IntegrationsTab(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.settings = load_settings()
        self.fields: dict[str, dict[str, QWidget]] = {}
        self.workers = []
        body = QWidget()
        layout = QVBoxLayout(body)
        note = QLabel("Settings are stored in ~/.qa_app/settings.json. In CI, pass secrets as environment "
                      "variables instead, e.g. QA_APP_JIRA_API_TOKEN. AWS uses your normal AWS credentials/profile.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#667")
        layout.addWidget(note)
        for name, defaults in DEFAULT_SETTINGS.items():
            box = QGroupBox(INTEGRATION_TITLES.get(name, name))
            form = QFormLayout(box)
            self.fields[name] = {}
            for key, default in defaults.items():
                value = self.settings[name].get(key, default)
                if isinstance(default, bool):
                    w = QCheckBox(checked=bool(value))
                else:
                    w = QLineEdit(str(value))
                    if key in SECRET_KEYS:
                        w.setEchoMode(QLineEdit.Password)
                self.fields[name][key] = w
                form.addRow(key.replace("_", " ").capitalize(), w)
            status = QLabel()
            status.setWordWrap(True)
            test = QPushButton("Test connection")
            test.clicked.connect(lambda _=False, n=name, s=status: self.test(n, s))
            row = QHBoxLayout()
            row.addWidget(test)
            row.addWidget(status, 1)
            form.addRow(row)
            layout.addWidget(box)
        save = QPushButton("Save settings")
        save.setStyleSheet("font-weight:600;padding:8px")
        save.clicked.connect(self.save)
        layout.addWidget(save)
        layout.addStretch()
        self.setWidget(body)

    def collect(self) -> dict:
        out = {}
        for name, fields in self.fields.items():
            out[name] = {k: (w.isChecked() if isinstance(w, QCheckBox) else w.text().strip()) for k, w in fields.items()}
        return out

    def save(self) -> None:
        save_settings(self.collect())
        QMessageBox.information(self, "QA App", "Settings saved.")

    def test(self, name: str, status: QLabel) -> None:
        status.setText("Testing…")
        status.setStyleSheet("")
        worker = TestConnectionWorker(name, self.collect()[name])
        worker.done.connect(lambda msg, ok: (status.setText(msg),
                                             status.setStyleSheet(f"color:{'#2e7d32' if ok else '#c62828'}")))
        self.workers.append(worker)
        worker.start()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"QA Engineer App {__version__}")
        self.resize(1400, 860)
        self.history = HistoryTab()
        self.run_tab = RunTab(self)
        tabs = QTabWidget()
        tabs.addTab(self.run_tab, "Run")
        tabs.addTab(self.history, "History")
        tabs.addTab(IntegrationsTab(), "Integrations")
        self.setCentralWidget(tabs)

"""Core data models shared by checks, reports and integrations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum


class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"

    @property
    def rank(self) -> int:
        return ["critical", "major", "minor", "info"].index(self.value)


@dataclass
class Finding:
    check: str            # e.g. "functional", "visual", "accessibility", "performance", "seo"
    title: str
    severity: Severity
    url: str
    details: str = ""
    screenshot: str | None = None   # path to an image on disk

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class PageResult:
    url: str
    status: int | None
    load_ms: int | None
    title: str = ""


@dataclass
class RunConfig:
    url: str
    checks: list[str] = field(default_factory=lambda: ["functional", "visual", "accessibility", "seo"])
    max_pages: int = 10
    viewports: list[str] = field(default_factory=lambda: ["desktop", "mobile"])
    visual_threshold: float = 0.5      # % of differing pixels allowed
    use_lighthouse: bool = True
    headless: bool = True
    update_baselines: bool = False


@dataclass
class RunResult:
    run_id: str
    config: RunConfig
    started: datetime
    finished: datetime | None = None
    pages: list[PageResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)   # e.g. lighthouse scores per url
    output_dir: str = ""
    report_path: str = ""

    def count(self, severity: Severity) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    @property
    def passed(self) -> bool:
        return self.count(Severity.CRITICAL) == 0 and self.count(Severity.MAJOR) == 0

    def summary_line(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        return (f"{status} — {self.config.url}: {len(self.pages)} pages, "
                f"{self.count(Severity.CRITICAL)} critical, {self.count(Severity.MAJOR)} major, "
                f"{self.count(Severity.MINOR)} minor")

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "config": asdict(self.config),
            "started": self.started.isoformat(),
            "finished": self.finished.isoformat() if self.finished else None,
            "passed": self.passed,
            "pages": [asdict(p) for p in self.pages],
            "findings": [f.to_dict() for f in self.findings],
            "metrics": self.metrics,
            "report_path": self.report_path,
        }

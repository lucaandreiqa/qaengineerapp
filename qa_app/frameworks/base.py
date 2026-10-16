"""What every framework adapter offers. A ticket's tests are written and run by one adapter, picked from the framework
profile onboarding found in the company's automation repo (frameworks.pick)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

STYLE_MAX = 12000   # style examples given to Claude when it writes a spec
SPEC_MAX = 4500     # per example spec file
SIG_LINES = 40      # signature lines per page object or helper file
HELPER = re.compile(r"(^|/)(page-?objects?|pages|po|helpers?|utils?|support|fixtures?|lib)(/|$)|(page|helper|fixture)s?\.[jt]sx?$", re.I)
SIGNATURE = re.compile(r"^\s*(export\s+(default\s+)?)?((async\s+)?function\s+\w+\s*\(.*|class\s+\w+.*|"
                       r"(const|let)\s+\w+\s*=\s*(async\s*)?\(.*=>.*|(public\s+|private\s+|static\s+|async\s+|get\s+)*\w+\s*\([^)]*\)\s*(:\s*[^{]+)?\{)")


def latest_repo_study(company: Path) -> Optional[dict]:
    """The automation repo as the most recent onboarding study read it (collected/repo.json), or None."""
    root = company / "onboarding"
    best, best_t = None, -1.0
    for d in root.iterdir() if root.exists() else []:
        f = d / "collected" / "repo.json"
        if not f.exists():
            continue
        try:
            started = float(json.loads((d / "summary.json").read_text(encoding="utf-8")).get("started") or 0)
        except (OSError, ValueError):
            started = 0.0
        if started > best_t:
            best, best_t = f, started
    try:
        return json.loads(best.read_text(encoding="utf-8")) if best else None
    except (OSError, ValueError):
        return None


def signatures(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        if SIGNATURE.match(line) and not re.match(r"^\s*(if|for|while|switch|catch|return)\b", line):
            out.append(line.rstrip().rstrip("{").rstrip())
        if len(out) >= SIG_LINES:
            break
    return out


class Adapter:
    name = ""
    label = ""
    spec_pattern = re.compile(r"$^")

    def matches(self, profile: dict) -> bool:
        raise NotImplementedError

    def style_examples(self, company: Path) -> str:
        """Up to 2 of the company's own test files and the signatures of their page objects and helpers."""
        study = latest_repo_study(company)
        if not study:
            return ""
        files: dict = study.get("files") or {}
        specs = [p for p in files if self.spec_pattern.search(p)][:2]
        parts = [f"===== {p}\n{files[p][:SPEC_MAX]}" for p in specs]
        for p, text in files.items():
            if p in specs or self.spec_pattern.search(p) or not HELPER.search(p):
                continue
            sigs = signatures(text)
            if sigs:
                parts.append(f"===== {p} (signatures only)\n" + "\n".join(sigs))
        out = ""
        for part in parts:
            if len(out) + len(part) + 2 > STYLE_MAX:
                break
            out += part + "\n\n"
        return out.strip()

"""Bounded, read-only samples from each source a company connects. Nothing here writes anywhere."""
from __future__ import annotations

import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Optional

DESC_MAX, COMMENT_MAX, COMMENTS = 2000, 400, 5
PAGE_MAX, REPO_CAP, FILE_MAX, TREE_MAX = 6000, 120_000, 6000, 3000
HEAVY = {"node_modules", ".git", "venv", ".venv", "env", "dist", "build", "__pycache__", "coverage", "test-results",
         "playwright-report", "allure-results", "allure-report", ".next", ".nuxt", "target", "bin", "obj", ".idea", ".vscode",
         ".pytest_cache", ".mypy_cache", ".tox", "vendor"}
SECRET = re.compile(r"(^|/)(\.env(\.[^/]*)?|.*\.(pem|key|p12|pfx)|credentials[^/]*|secrets?\.[^/]*)$", re.I)
CONFIG = re.compile(r"(^|/)(package\.json|tsconfig\.json|(playwright|cypress|wdio|jest|vitest)\.config\.[cm]?[jt]s|pytest\.ini|"
                    r"pyproject\.toml|setup\.cfg|tox\.ini|conftest\.py|requirements[^/]*\.txt|Pipfile|behave\.ini|"
                    r"\.env\.example|pom\.xml|build\.gradle)$", re.I)
CI = re.compile(r"(^\.github/workflows/.+\.ya?ml|^\.gitlab-ci\.yml|^azure-pipelines[^/]*\.ya?ml|^Jenkinsfile|"
                r"^bitbucket-pipelines\.yml|^\.circleci/config\.yml)$", re.I)
DOC = re.compile(r"^(README|CONTRIBUTING)[^/]*$|^docs/[^/]+\.md$", re.I)
TEST = re.compile(r"(\.(spec|test|cy)\.[cm]?[jt]sx?|(^|/)test_[^/]+\.py|_test\.py|\.feature|\.robot)$", re.I)
PAGEOBJ = re.compile(r"(^|/)(page[_-]?objects?|pages|po|pom|screens)/", re.I)
HELPER = re.compile(r"(^|/)(helpers?|utils?|support|fixtures?|common|lib)/", re.I)
SOURCE = re.compile(r"\.([cm]?[jt]sx?|py|java|cs|rb|feature|robot)$", re.I)


class OnboardingError(Exception):
    """A message for the user."""


def brief_ticket(raw: dict) -> dict:
    """A tracker issue (Jira-shaped: {key, fields}) in the small shape onboarding studies."""
    from ..workflow.ticket_context import text
    f = raw.get("fields") or {}

    def name(v: Any) -> str:
        return (v or {}).get("name", "") if isinstance(v, dict) else str(v or "")
    comments = ((f.get("comment") or {}).get("comments") or []) if isinstance(f.get("comment"), dict) else (f.get("comment") or [])
    bodies = [text(c.get("body") if isinstance(c, dict) else c).strip() for c in comments]
    return {"key": raw.get("key", ""), "title": f.get("summary", ""), "type": name(f.get("issuetype")),
            "status": name(f.get("status")), "priority": name(f.get("priority")),
            "components": [name(c) for c in f.get("components") or [] if name(c)], "labels": list(f.get("labels") or []),
            "description": text(f.get("description")).strip()[:DESC_MAX],
            "comments": [b[:COMMENT_MAX] for b in bodies if b][-COMMENTS:]}


def collect_tracker(client, projects: list[str], limit: int = 200, on_project=None) -> dict:
    """Recent tickets per project, and what the sample shows: statuses, components, labels, types, transitions.
    on_project(project, count) is called as each project is read (for the progress bar)."""
    tickets: list[dict] = []
    for p in projects:
        got = client.recent(p, limit)
        tickets += got
        if on_project:
            on_project(p, len(got))
    count = lambda field: dict(sorted(Counter(v for t in tickets for v in (t[field] if isinstance(t[field], list) else [t[field]]) if v).items()))
    transitions: dict[str, list[str]] = {}
    for status in list(count("status"))[:12]:
        key = next(t["key"] for t in tickets if t["status"] == status)
        try:
            transitions[status] = [tr["name"] for tr in client.get_transitions(key)]
        except Exception:
            transitions[status] = []
    return {"tickets": tickets, "statuses": count("status"), "components": count("components"), "labels": count("labels"),
            "types": count("type"), "transitions": transitions}


def collect_testrail(cfg: dict, limit: int = 150) -> dict:
    from ..integrations import testrail
    return testrail.sample(cfg, limit)


def collect_confluence(reader, ticket_texts: list[str], spaces: list[str], limit: int = 30) -> dict:
    """Pages linked from the tickets first, then the latest pages of the chosen spaces; each trimmed."""
    from ..integrations.confluence import PAGE_URL
    pages: list[dict] = []
    seen: set[str] = set()
    linked = []
    for text in ticket_texts:
        for m in re.finditer(r"https?://[^\s)>\]\"'|]+", text or ""):
            u = m.group(0).rstrip(".,;:")
            if PAGE_URL.search(u) and u not in linked:
                linked.append(u)
    for u in linked[:limit]:
        try:
            pg = reader.page(url=u)
        except Exception:
            continue
        pages.append({**pg, "text": str(pg.get("text", ""))[:PAGE_MAX]})
        seen.add((PAGE_URL.search(u).group(1) or u))  # type: ignore[union-attr]
    if spaces and len(pages) < limit:
        quoted = ", ".join(f'"{x}"' for x in spaces)
        for h in reader.search(f"space in ({quoted}) AND type = page ORDER BY lastmodified DESC", limit=min(50, limit)):
            if len(pages) >= limit:
                break
            if h.get("id") in seen:
                continue
            try:
                pg = reader.page(url=h.get("url", ""), page_id=h.get("id", ""))
            except Exception:
                continue
            pages.append({**pg, "text": str(pg.get("text", ""))[:PAGE_MAX]})
            seen.add(h.get("id"))
    return {"pages": pages}


def _is_url(source: str) -> bool:
    return bool(re.match(r"^(https?://|git@|ssh://)", source.strip()))


def repo_folder(source: str, workdir: Path) -> Path:
    """The local folder to study: the given folder, or a read-only shallow clone of the given link."""
    source = (source or "").strip()
    if not source:
        raise OnboardingError("No automation repo given.")
    if _is_url(source):
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", source.rstrip("/").split("/")[-1].removesuffix(".git")) or "repo"
        dest = workdir / name
        workdir.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            r = subprocess.run(["git", "-C", str(dest), "pull", "--ff-only", "--depth", "1"], capture_output=True, text=True, timeout=300)
        else:
            r = subprocess.run(["git", "clone", "--depth", "1", source, str(dest)], capture_output=True, text=True, timeout=300,
                               env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if r.returncode != 0 and not dest.exists():
            raise OnboardingError(f"Couldn't clone {source}: {(r.stderr or r.stdout).strip().splitlines()[-1:] or ['git failed']}")
        return dest
    p = Path(source).expanduser()
    if not p.is_dir():
        raise OnboardingError(f"Automation folder not found: {p}")
    return p


def collect_repo(source: str, workdir: Path) -> dict:
    """The repo's map and a capped selection of the files that show how it works: configs, CI, docs, then real
    specs, page objects and helpers (most recent first, at least one per folder). Secrets and heavy folders stay out."""
    root = repo_folder(source, workdir)
    all_files: list[tuple[str, float]] = []
    skipped: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        keep = []
        for d in dirnames:
            if d in HEAVY:
                skipped.append(d if rel_dir == "." else f"{rel_dir}/{d}")
            else:
                keep.append(d)
        dirnames[:] = sorted(keep)
        for f in filenames:
            rel = f if rel_dir == "." else f"{rel_dir}/{f}"
            try:
                all_files.append((rel, (Path(dirpath) / f).stat().st_mtime))
            except OSError:
                pass
    tree = sorted(r for r, _ in all_files)[:TREE_MAX]
    by_recent = [r for r, _ in sorted(all_files, key=lambda x: -x[1]) if not SECRET.search(r)]
    groups = [
        [r for r in tree if CONFIG.search(r) and r.count("/") <= 2 and not SECRET.search(r)],
        [r for r in tree if CI.search(r)],
        [r for r in tree if DOC.search(r)],
    ]
    code: list[str] = []
    for pattern in (TEST, PAGEOBJ, HELPER):
        picked, folders = [], set()
        for r in by_recent:
            if not SOURCE.search(r) or not pattern.search(r) or r in code:
                continue
            folder = r.rsplit("/", 1)[0] if "/" in r else ""
            if folder not in folders or len(picked) < 4:
                picked.append(r)
                folders.add(folder)
            if len(picked) >= 25:
                break
        code += picked
    files: dict[str, str] = {}
    total = 0
    for rel in [r for g in groups for r in g] + code:
        if rel in files:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")[:FILE_MAX]
        except OSError:
            continue
        if total + len(text) > REPO_CAP:
            skipped.append(f"{rel} (over the size cap)")
            continue
        files[rel] = text
        total += len(text)
    return {"root": str(root), "tree": tree, "files": files, "skipped": skipped[:200]}

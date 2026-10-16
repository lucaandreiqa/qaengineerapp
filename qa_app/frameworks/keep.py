"""Keep a finished ticket's tests on a local branch, yourqa/<KEY>, in the workspace.

Done with git plumbing and a temporary index: the workspace's checked-out branch, its index and its files are never
touched, and nothing is pushed.
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional


class KeepError(Exception):
    """Why the tests weren't kept (shown in the ticket feed)."""


def _git(cwd: Path, *args: str, env: Optional[dict] = None, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=60)
    if check and p.returncode != 0:
        raise KeepError(f"git {args[0]} failed: {(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout.strip()


def _is_repo(ws: Path) -> bool:
    try:
        return subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ws, capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def branch_name(key: str) -> str:
    return "yourqa/" + re.sub(r"[^A-Za-z0-9._-]", "-", key)


def commit_ticket(workspace: Path, key: str, message: str, init: bool = False) -> str:
    """Commit tests/tickets/<KEY>/ as it is now to yourqa/<KEY>; returns the commit. init: create the repository if
    the workspace isn't one (only for YourQA's own workspace)."""
    ws = Path(workspace)
    folder = ws / "tests" / "tickets" / key
    files = sorted(p for p in folder.rglob("*") if p.is_file()) if folder.exists() else []
    if not files:
        raise KeepError(f"No test files for {key} in {folder}")
    if not _is_repo(ws):
        if not init:
            raise KeepError(f"{ws} is not a git repository")
        _git(ws, "init", "-q", "-b", "main")
    top = Path(_git(ws, "rev-parse", "--show-toplevel")).resolve()
    git_dir = Path(_git(ws, "rev-parse", "--absolute-git-dir"))
    rel_folder = folder.resolve().relative_to(top).as_posix()
    ref = "refs/heads/" + branch_name(key)
    parent = _git(top, "rev-parse", "--verify", "-q", ref, check=False)
    index = git_dir / f"yourqa-index-{uuid.uuid4().hex}"
    env = {"GIT_INDEX_FILE": str(index)}
    if not _git(top, "config", "user.name", check=False):
        env.update(GIT_AUTHOR_NAME="YourQA", GIT_COMMITTER_NAME="YourQA")
    if not _git(top, "config", "user.email", check=False):
        env.update(GIT_AUTHOR_EMAIL="yourqa@localhost", GIT_COMMITTER_EMAIL="yourqa@localhost")
    try:
        if parent:
            _git(top, "read-tree", parent, env=env)
            for old in _git(top, "ls-files", "--", rel_folder, env=env).splitlines():  # files since removed go too
                _git(top, "update-index", "--force-remove", "--", old, env=env)
        else:
            _git(top, "read-tree", "--empty", env=env)
        for f in files:
            sha = _git(top, "hash-object", "-w", "--", str(f))
            mode = "100755" if os.access(f, os.X_OK) else "100644"
            _git(top, "update-index", "--add", "--cacheinfo", f"{mode},{sha},{f.resolve().relative_to(top).as_posix()}", env=env)
        tree = _git(top, "write-tree", env=env)
        if parent and _git(top, "rev-parse", f"{parent}^{{tree}}") == tree:
            return parent  # nothing changed since the last time
        commit = _git(top, "commit-tree", tree, *(["-p", parent] if parent else []), "-m", message, env=env)
        _git(top, "update-ref", ref, commit, *([parent] if parent else []))
        return commit
    finally:
        index.unlink(missing_ok=True)

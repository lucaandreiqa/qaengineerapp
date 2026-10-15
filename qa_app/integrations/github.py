"""GitHub, read-only: pull requests linked to a ticket (description, commits, changed files, review comments) and a
search for PRs that mention the ticket key. Used to give Claude the real change behind a ticket. Nothing here writes.

The user pastes their own fine-grained token (read-only: Contents, Pull requests, Metadata)."""
from __future__ import annotations

import re
from typing import Optional

import requests

API = "https://api.github.com"
PR_URL = re.compile(r"https?://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)", re.I)


class GitHubError(Exception):
    pass


class GitHub:
    def __init__(self, token: str, http: Optional[requests.Session] = None, api: str = API) -> None:
        if not (token or "").strip():
            raise GitHubError("GitHub is not connected: add a token on the Integrations screen.")
        self.api = api.rstrip("/")
        self.s = http or requests.Session()
        self.h = {"Authorization": f"Bearer {token.strip()}", "Accept": "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "YourQA"}

    def _get(self, path: str, **params) -> object:
        try:
            r = self.s.get(self.api + path, headers=self.h, params=params or None, timeout=30)
        except requests.RequestException as e:
            raise GitHubError(f"Can't reach GitHub: {e.__class__.__name__}") from e
        if r.status_code == 401:
            raise GitHubError("GitHub rejected the token (HTTP 401). Create a new one and paste it on the Integrations screen.")
        if r.status_code in (403, 404):
            raise GitHubError(f"GitHub: not found or no access (HTTP {r.status_code}) for {path}. Check the token's repository access.")
        if not r.ok:
            raise GitHubError(f"GitHub error (HTTP {r.status_code}): {r.text[:200]}")
        return r.json()

    def me(self) -> str:
        return str((self._get("/user") or {}).get("login", ""))  # type: ignore[union-attr]

    def pr(self, owner: str, repo: str, number: int, max_files: int = 100) -> dict:
        base = f"/repos/{owner}/{repo}/pulls/{number}"
        p = self._get(base)
        assert isinstance(p, dict)
        commits = self._get(base + "/commits", per_page=100)
        files: list = []
        for page in (1, 2, 3):
            chunk = self._get(base + "/files", per_page=100, page=page)
            files += chunk if isinstance(chunk, list) else []
            if not isinstance(chunk, list) or len(chunk) < 100 or len(files) >= max_files:
                break
        review = self._get(base + "/comments", per_page=100)
        talk = self._get(f"/repos/{owner}/{repo}/issues/{number}/comments", per_page=100)
        return {
            "repo": f"{owner}/{repo}", "number": int(number), "url": p.get("html_url", ""), "title": p.get("title", ""),
            "state": "merged" if p.get("merged_at") else p.get("state", ""), "branch": (p.get("head") or {}).get("ref", ""),
            "base": (p.get("base") or {}).get("ref", ""), "author": (p.get("user") or {}).get("login", ""),
            "body": p.get("body") or "",
            "commits": [{"sha": c.get("sha", "")[:7], "message": ((c.get("commit") or {}).get("message") or "").strip()}
                        for c in (commits if isinstance(commits, list) else [])],
            "files": [{"name": f.get("filename", ""), "status": f.get("status", ""), "additions": f.get("additions", 0),
                       "deletions": f.get("deletions", 0), "patch": f.get("patch") or ""} for f in files[:max_files]],
            "review_comments": [{"author": (c.get("user") or {}).get("login", ""), "file": c.get("path", ""), "body": c.get("body", "")}
                                for c in (review if isinstance(review, list) else [])],
            "comments": [{"author": (c.get("user") or {}).get("login", ""), "body": c.get("body", "")}
                         for c in (talk if isinstance(talk, list) else [])],
        }

    def search_prs(self, text: str, scope: list[str], limit: int = 5) -> list[dict]:
        """PRs whose title, body or branch mention the text (the ticket key), in the repos / orgs listed in scope."""
        q = f'"{text}" type:pr ' + " ".join(f"repo:{s}" if "/" in s else f"org:{s}" for s in scope if s)
        res = self._get("/search/issues", q=q.strip(), per_page=limit, sort="updated")
        out = []
        for i in (res.get("items", []) if isinstance(res, dict) else [])[:limit]:
            m = PR_URL.search(i.get("html_url", ""))
            if m:
                out.append({"owner": m.group(1), "repo": m.group(2), "number": int(m.group(3)), "title": i.get("title", ""),
                            "url": i.get("html_url", "")})
        return out


def scope(cfg: dict) -> list[str]:
    return [s.strip().strip("/") for s in re.split(r"[,\s]+", str(cfg.get("repos") or "")) if s.strip()]


def test_connection(cfg: dict) -> str:
    gh = GitHub(cfg.get("token", ""))
    who = gh.me()
    sc = scope(cfg)
    return f"Signed in as {who}" + (f" · searching {', '.join(sc)}" if sc else " · ticket-key search needs repos or orgs listed")

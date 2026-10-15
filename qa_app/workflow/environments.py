"""Find where to test a ticket, from what the ticket itself says. No company-specific rules.

Every link on the ticket is a candidate: the Environment field, custom fields, web links, comments (newest
first) and the description. Each gets a score from

  where it is     Environment field > env-like custom field > web link > comment (newer higher) > description
  what's around   "preview", "staging", "deployed to", "test on", "environment", "QA"… on the same line
  what it is      preview / staging / qa / pr-123 style hosts, hosting platforms (vercel.app, netlify.app, …),
                  and the team's own hints from settings (e.g. their preview domain)

Links that are clearly not an environment (the Jira site, code hosts, design and docs tools, files) are dropped,
and production-looking links are marked down. The best candidate is used only when the evidence is clear;
otherwise the ticket stops at "Needs environment" and lists what was found, so the user picks.
API links (api.…, /api, /graphql) are paired with the app link, or used on their own for BE tickets.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import urlparse

URL = re.compile(r"""https?://[^\s<>()\[\]{}"'`|\\^]+""", re.I)
# An address typed without http(s)://, e.g. "www.google.com" or "staging.myapp.io/login" (not part of an e-mail or a longer word).
BARE = re.compile(r"""(?<![\w@/.:-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:com|net|org|io|dev|app|co|ai|cloud|tech|site|online|"""
                  r"""shop|store|eu|uk|de|ro|fr|nl|es|it|pl|se|ch|at|be|us|ca|au|in|jp|test|local)(?::\d+)?"""
                  r"""(?:/[^\s<>()\[\]{}"'`|\\^]*)?)(?![\w-])""", re.I)
NOT_ENV_HOSTS = ("atlassian.net", "atlassian.com", "jira.com", "github.com", "githubusercontent.com", "gitlab.com", "bitbucket.org",
                 "figma.com", "docs.google.com", "drive.google.com", "sheets.google.com", "slack.com", "loom.com", "miro.com",
                 "notion.so", "notion.site", "sentry.io", "zoom.us", "teams.microsoft.com", "sharepoint.com", "dropbox.com",
                 "youtube.com", "youtu.be", "stackoverflow.com", "trello.com", "linear.app", "lucid.app",
                 "postman.com", "npmjs.com", "pypi.org", "wikipedia.org",
                 # tools and help pages on big sites, not the sites themselves (www.google.com can be what you test)
                 "meet.google.com", "calendar.google.com", "mail.google.com", "forms.google.com", "photos.google.com",
                 "support.google.com", "accounts.google.com", "support.apple.com", "developer.apple.com",
                 "learn.microsoft.com", "support.microsoft.com", "outlook.office.com", "office.com")
FILE_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp|pdf|zip|gz|mp4|mov|webm|csv|xlsx?|docx?|pptx?|txt|log|har|json)$", re.I)
ENV_WORDS = re.compile(r"\b(preview|staging|stage|stg|uat|qa\b|test(ing)? (env|on|here|at)|environment|env\b|(re)?deploy(ed|ment)?|"
                       r"review app|sandbox|available (at|on)|live (at|on)|try (it )?(at|on|here)|ready (for|to) (qa|test)|pr env)", re.I)
HOST_HINT = re.compile(r"(^|[.-])(preview|staging|stage|stg|qa|uat|test|testing|dev|develop|sandbox|review|feature|feat|branch|"
                       r"pr-?\d+|demo|tmp|canary|beta)([.-]|\d|$)", re.I)
PLATFORMS = ("vercel.app", "netlify.app", "pages.dev", "workers.dev", "herokuapp.com", "onrender.com", "fly.dev", "amplifyapp.com",
             "azurewebsites.net", "azurestaticapps.net", "web.app", "firebaseapp.com", "github.io", "railway.app", "surge.sh",
             "ngrok-free.app", "ngrok.io", "ngrok.app", "loca.lt", "trycloudflare.com")
PROD_WORDS = re.compile(r"\b(prod|production|live site|customers?)\b", re.I)
AUTO_PICK = 55  # below this the user chooses


@dataclass
class Candidate:
    url: str
    source: str          # where it was found, for the user
    score: int
    why: list[str] = field(default_factory=list)
    api: bool = False
    prod: bool = False

    def public(self) -> dict:
        return asdict(self)


def _clean(u: str) -> str:
    u = u.rstrip(".,;:!?*_~'\"")
    while u.endswith(")") and u.count("(") < u.count(")"):
        u = u[:-1]
    return u


def _links(text: str) -> list[tuple[str, str]]:
    """(url, the line around it) for every link in a block of text, including addresses typed without https://."""
    out = []
    for line in (text or "").splitlines():
        for m in URL.finditer(line):
            out.append((_clean(m.group(0)), line))
        rest = URL.sub(" ", line)
        for m in BARE.finditer(rest):
            out.append(("https://" + _clean(m.group(1)), line))
    return out


def _only_link(text: str, url: str) -> bool:
    """The whole text is this one link (how people often post 'test here')."""
    left = URL.sub(" ", text or "")
    left = BARE.sub(" ", left)
    left = re.sub(r"[\[\]()<>|*_~`:.,;!?\-\s]", "", left)
    bare = re.sub(r"^https?://", "", url).rstrip("/").lower()
    return not left or left.lower() == bare.replace("/", "")


def _is_api(u: str) -> bool:
    p = urlparse(u)
    return p.hostname is not None and (p.hostname.startswith(("api.", "api-", "gateway.", "graphql.")) or
                                       bool(re.search(r"/(api|graphql|swagger|openapi)(/|$)", p.path, re.I)))


def _score(url: str, line: str, base: int, source: str, hints: list[str], jira_host: str) -> Optional[Candidate]:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if not host or "." not in host and host != "localhost":
        return None
    if host == jira_host or "confluence" in host or any(host == h or host.endswith("." + h) for h in NOT_ENV_HOSTS):
        return None
    if FILE_EXT.search(p.path):
        return None
    c = Candidate(url=url if p.path not in ("", "/") or url.endswith("/") else url + "/", source=source, score=base, api=_is_api(url))
    if ENV_WORDS.search(line.replace(url, " ")):
        c.score += 25; c.why.append("mentioned as an environment")
    if HOST_HINT.search(host.split(".")[0]) or HOST_HINT.search(host):
        c.score += 20; c.why.append("test-style address")
    if any(host.endswith(pl) for pl in PLATFORMS):
        c.score += 15; c.why.append("preview hosting")
    for h in hints:
        if h and (h in host or h in url.lower()):
            c.score += 30; c.why.append(f"matches your hint '{h}'")
            break
    if host in ("localhost", "127.0.0.1") or host.endswith(".local"):
        c.score -= 40; c.why.append("only on someone's computer")
    if PROD_WORDS.search(line) and not ENV_WORDS.search(line):
        c.score -= 40; c.prod = True; c.why.append("looks like production")
    return c


def find(ctx: dict, hints: Optional[list[str]] = None, jira_host: str = "") -> list[Candidate]:
    """Every link on the ticket that could be a test environment, best first (one entry per URL)."""
    hints = [h.strip().lower() for h in hints or [] if h.strip()]
    found: list[Candidate] = []

    def add(text: str, base: int, source: str, lone_bonus: bool = False) -> None:
        links = _links(text)
        for url, line in links:
            c = _score(url, line, base, source, hints, jira_host)
            if c:
                if lone_bonus and len({re.sub(r"^https?://", "", u).rstrip("/").lower() for u, _ in links}) == 1 and _only_link(text, url):
                    c.score += 15; c.why.append("the comment is just this link")
                found.append(c)

    add(ctx.get("environment", ""), 60, "Environment field")
    for name, value in (ctx.get("fields") or {}).items():
        env_named = re.search(r"env|url|preview|staging|deploy|link|site", name, re.I)
        add(f"{name}: {value}", 50 if env_named else 30, f"field '{name}'")  # the field's name counts as context
    for w in ctx.get("web_links") or []:
        title = w.get("title", "")
        add(f"{title} {w.get('url', '')}", 35, f"web link '{title}'" if title else "web link")
    comments = ctx.get("comments") or []
    for i, cm in enumerate(reversed(comments)):  # newest first: a later deploy replaces an earlier one
        who = cm.get("author") or "someone"
        add(cm.get("body", ""), 30 + max(0, 12 - 3 * i), f"comment by {who}" + (f" · {cm['created']}" if cm.get("created") else ""),
            lone_bonus=True)
    add(ctx.get("description", ""), 25, "description")
    add(ctx.get("acceptance_criteria", ""), 25, "acceptance criteria")

    best: dict[str, Candidate] = {}
    for c in found:  # keep the strongest sighting of each URL
        key = re.sub(r"^https?://", "", c.url).rstrip("/").lower()  # http and https are the same address here
        if key not in best or c.score > best[key].score:
            best[key] = c
    return sorted(best.values(), key=lambda c: -c.score)


def choose(candidates: list[Candidate], ticket_type: str = "") -> tuple[Optional[Candidate], Optional[Candidate]]:
    """(app link, API link) to test with, or (None, None) when no candidate is clear enough."""
    apps = [c for c in candidates if not c.api and not c.prod]
    apis = [c for c in candidates if c.api and not c.prod]
    be_only = ticket_type == "BE"
    primary = (apis[0] if be_only and apis else apps[0] if apps else apis[0] if apis else None)
    if not primary or primary.score < AUTO_PICK:
        return None, None
    api = None
    if not primary.api and apis:
        host = urlparse(primary.url).hostname or ""
        root = ".".join(host.split(".")[-2:])
        same = [a for a in apis if (urlparse(a.url).hostname or "").endswith(root) or a.source == primary.source]
        api = (same or [None])[0]
    return primary, api


def looks_released(ctx: dict, merged: bool) -> bool:
    """The change is in the shared environment: merged, or the ticket says so by its status."""
    st = (ctx.get("status") or "").lower()
    return merged or any(w in st for w in ("merged", "done", "closed", "released", "deployed", "resolved"))

"""Framework adapters: which adapter writes and runs a ticket's tests, the company's style, and keeping tests on a branch."""
from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

from qa_app import frameworks
from qa_app.frameworks import keep


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_playwright_profiles_get_the_playwright_adapter_and_others_a_note():
    a, note = frameworks.pick({"language": "TypeScript", "framework": "Playwright", "runner": "@playwright/test"})
    assert a.name == "playwright-ts" and note == ""
    a, note = frameworks.pick({"language": "JavaScript", "framework": "Cypress", "runner": "cypress run"})
    assert a.name == "playwright-ts" and "Cypress" in note and "Playwright" in note
    a, note = frameworks.pick({"language": "Python", "framework": "pytest + selenium"})
    assert a.name == "playwright-ts" and "pytest + selenium" in note
    assert frameworks.pick({}) == (frameworks.ADAPTERS[0], "")


def _study(company, run_id, started, files):
    d = company / "onboarding" / run_id
    (d / "collected").mkdir(parents=True)
    (d / "summary.json").write_text(json.dumps({"id": run_id, "started": started}))
    (d / "collected" / "repo.json").write_text(json.dumps({"root": "/r", "tree": list(files), "files": files}))


def test_style_examples_come_from_the_latest_study_of_the_repo(tmp_path):
    company = tmp_path / "company"
    assert frameworks.ADAPTERS[0].style_examples(company) == ""          # no onboarding yet
    _study(company, "old", 1, {"tests/old.spec.ts": "test('old style', () => {})"})
    spec = "import { test } from '../fixtures';\n" + "test.describe('@smoke Checkout', () => {\n  test('pays', async ({ page }) => {});\n});\n"
    _study(company, "new", 2, {
        "package.json": '{"devDependencies": {"@playwright/test": "1.48"}}',
        "tests/checkout.spec.ts": spec,
        "tests/login.spec.ts": "test('logs in', async () => {})",
        "tests/cart.spec.ts": "test('third spec is left out', async () => {})",
        "pageObjects/LoginPage.ts": "export class LoginPage {\n  constructor(page) { this.page = page; }\n"
                                    "  async signIn(user: string) {\n    await this.page.fill('#u', user);\n  }\n}\n",
        "helpers/data.ts": "export function uniqueName(prefix: string) { return prefix + Date.now(); }\nconst secret = 1;\n",
    })
    out = frameworks.ADAPTERS[0].style_examples(company)
    assert "@smoke Checkout" in out and "old style" not in out                   # the latest study
    assert out.count("===== tests/") == 2 and "third spec" not in out           # at most 2 specs
    assert "class LoginPage" in out and "async signIn(user: string)" in out      # signatures, not bodies
    assert "page.fill('#u'" not in out and "export function uniqueName(prefix: string)" in out
    assert len(out) <= frameworks.STYLE_MAX


@pytest.fixture()
def repo(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    git(ws, "config", "user.email", "me@example.com")
    git(ws, "config", "user.name", "Me")
    (ws / "README.md").write_text("mine\n")
    git(ws, "add", ".")
    git(ws, "commit", "-q", "-m", "init")
    (ws / "README.md").write_text("mine, edited and not committed\n")      # your work in progress
    d = ws / "tests" / "tickets" / "OPTR-1"
    d.mkdir(parents=True)
    (d / "OPTR-1.spec.ts").write_text("test('[1] a', async () => {})\n")
    (d / "OPTR-1-qa-checklist.md").write_text("- [x] a\n")
    return ws


def test_a_finished_ticket_is_committed_on_its_branch_without_touching_your_checkout(repo):
    before = (git(repo, "rev-parse", "--abbrev-ref", "HEAD"), git(repo, "status", "--porcelain"))
    sha = keep.commit_ticket(repo, "OPTR-1", "QA OPTR-1: A (1 passed, 0 failed)")
    assert git(repo, "rev-parse", "yourqa/OPTR-1") == sha
    assert git(repo, "show", "--name-only", "--format=%s", sha).splitlines()[0] == "QA OPTR-1: A (1 passed, 0 failed)"
    files = git(repo, "ls-tree", "-r", "--name-only", sha).splitlines()
    assert files == ["tests/tickets/OPTR-1/OPTR-1-qa-checklist.md", "tests/tickets/OPTR-1/OPTR-1.spec.ts"]
    assert (git(repo, "rev-parse", "--abbrev-ref", "HEAD"), git(repo, "status", "--porcelain")) == before
    # a second finish adds a commit on top
    (repo / "tests" / "tickets" / "OPTR-1" / "OPTR-1.spec.ts").write_text("test('[1] b', async () => {})\n")
    sha2 = keep.commit_ticket(repo, "OPTR-1", "QA OPTR-1 again")
    assert git(repo, "rev-parse", f"{sha2}^") == sha


def test_a_folder_that_isnt_a_repository_is_left_alone_unless_its_yourqas(tmp_path):
    ws = tmp_path / "plain"
    (ws / "tests" / "tickets" / "OPTR-2").mkdir(parents=True)
    (ws / "tests" / "tickets" / "OPTR-2" / "OPTR-2.spec.ts").write_text("x")
    with pytest.raises(keep.KeepError, match="not a git repository"):
        keep.commit_ticket(ws, "OPTR-2", "m")
    assert not (ws / ".git").exists()
    sha = keep.commit_ticket(ws, "OPTR-2", "m", init=True)
    assert git(ws, "rev-parse", "yourqa/OPTR-2") == sha


def test_nothing_to_keep_is_an_error_not_an_empty_commit(repo):
    with pytest.raises(keep.KeepError, match="No test files"):
        keep.commit_ticket(repo, "OPTR-9", "m")


def test_the_spec_prompt_has_the_company_style_and_says_not_to_import_it(tmp_path, monkeypatch):
    from qa_app import config
    from qa_app.workflow import agent
    from qa_app.workflow.models import CheckItem, Env, Section, Ticket
    from qa_app.workflow.settings import WorkflowConfig as Config
    company = tmp_path / "company"
    monkeypatch.setattr(config, "company_dir", lambda: company)
    _study(company, "r", 1, {"tests/checkout.spec.ts": "test.describe('@smoke Checkout', () => {})"})
    seen = {}

    async def fake(cfg, system, prompt, max_tokens=4000, step=None):
        seen["prompt"] = prompt
        return "import { test } from '@playwright/test';\ntest('[1] a', async () => {});\n"
    monkeypatch.setattr(agent, "ask_claude", fake)
    cfg = Config(demo=False, anthropic_api_key="k", data_dir=tmp_path, workspace=tmp_path / "ws")
    t = Ticket(key="OPTR-3", title="T", env=Env(kind="Test environment", url="https://x.test/"),
               checklist=[Section(name="A", items=[CheckItem(text="a")])])
    asyncio.new_event_loop().run_until_complete(agent.build_spec(cfg, t))
    assert "@smoke Checkout" in seen["prompt"] and "never import" in seen["prompt"].lower()

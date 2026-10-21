"""Onboarding study runs: collect, analyse, apply area by area, report; one at a time; used by every step."""
from __future__ import annotations

import asyncio
import json

import pytest

from qa_app import config
from qa_app.onboarding import run as ob
from qa_app.workflow import agent, skills, store
from qa_app.workflow.clients import MockJira
from qa_app.workflow.settings import WorkflowConfig as Config
from tests.test_onboarding_analyze import ANSWERS, fake_claude


def go(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "company_dir", lambda: tmp_path / "company")
    monkeypatch.setattr(skills, "root", lambda: tmp_path / "skills")
    events = []
    monkeypatch.setattr(store.bus, "publish", lambda ev: events.append(ev))
    calls = []
    monkeypatch.setattr(agent, "ask_claude", fake_claude(calls))
    return tmp_path, events, calls


def _issues(n):
    return [{"key": f"SCRUM-{i}", "title": f"T{i}", "status": "Testing", "issue_type": "Story", "updated": f"2026-10-{i % 28 + 1:02d}",
             "components": ["Frontend"], "description": "Acceptance criteria:\n- works"} for i in range(n)]


def _sources(tmp, with_repo=True, tracker=True):
    repo = tmp / "repo"
    if with_repo:
        (repo / "tests").mkdir(parents=True, exist_ok=True)
        (repo / "package.json").write_text('{"devDependencies": {"@playwright/test": "1"}}')
        (repo / "tests" / "a.spec.ts").write_text("test('a', async () => {})")
    return lambda: {"cfg": Config(demo=False, anthropic_api_key="k"), "tracker": MockJira(_issues(60)) if tracker else None,
                    "testrail": None, "confluence": None}, str(repo)


def test_a_study_collects_analyses_applies_and_reports(home):
    tmp, events, calls = home
    factory, repo = _sources(tmp)
    o = ob.Onboarding(factory)
    run_id = go(o.study({"projects": ["SCRUM"], "spaces": [], "repo": repo}))
    st = o.state()
    last = st["last"]
    assert last["id"] == run_id and last["status"] == "done" and not st["running"]
    assert last["sources"]["tracker"].startswith("Read 60 tickets") and last["sources"]["testrail"] == "not connected"
    assert last["sources"]["repo"].startswith("Read")
    targets = {c["target"] for c in last["changes"]}
    assert {"workflow.jira_column", "SCRUM/gather", "company/knowledge.md", "company/profile.json", "SCRUM/create-tests"} <= targets
    assert (tmp / "company" / "onboarding" / run_id / "collected" / "tracker.json").exists()   # what was studied is kept
    assert any(e.get("type") == "onboarding" and e.get("event") == "done" for e in events)
    o.undo_all()
    assert config.load_settings()["workflow"]["jira_column"] == "Testing" and skills.project("SCRUM", "gather") is None


def test_a_missing_source_is_skipped_and_listed(home):
    tmp, events, calls = home
    factory, repo = _sources(tmp, with_repo=False)
    o = ob.Onboarding(factory)
    go(o.study({"projects": ["SCRUM"], "spaces": [], "repo": str(tmp / "nope")}))
    last = o.state()["last"]
    assert last["status"] == "done" and last["sources"]["repo"].startswith("failed") and "not found" in last["sources"]["repo"].lower()
    assert any(c["target"] == "SCRUM/gather" for c in last["changes"])   # the tracker part still applied


def test_only_one_study_at_a_time_and_an_interrupted_run_is_marked_stopped(home):
    tmp, events, calls = home
    factory, repo = _sources(tmp)
    o = ob.Onboarding(factory)

    async def both():
        first = asyncio.ensure_future(o.study({"projects": ["SCRUM"], "spaces": [], "repo": repo}))
        await asyncio.sleep(0)
        with pytest.raises(ob.OnboardingBusy):
            await o.study({"projects": ["SCRUM"], "spaces": [], "repo": repo})
        await first
    go(both())
    run_dir = tmp / "company" / "onboarding" / "r-crashed"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(json.dumps({"id": "r-crashed", "started": 9e12, "status": "running", "sources": {}, "changes": []}))
    assert ob.Onboarding(factory).state()["last"]["status"] == "stopped"


def test_knowledge_reaches_every_step_prompt_and_the_profile_reaches_test_writing(home):
    tmp, events, calls = home
    (tmp / "company").mkdir()
    (tmp / "company" / "knowledge.md").write_text("# Company\nOU = organization unit.")
    (tmp / "company" / "profile.json").write_text(json.dumps({"framework": "Playwright", "language": "TypeScript"}))
    cfg = Config(demo=False, anthropic_api_key="k")
    sys_text = agent.system("base", "gather", cfg)
    assert "<company_knowledge>" in sys_text and "OU = organization unit" in sys_text
    assert "Playwright" in agent.framework_note()


def test_connected_mcp_servers_are_studied_with_read_tools_only(home, monkeypatch):
    from qa_app.integrations import mcp_servers as ms
    tmp, events, calls = home
    ran = []

    class Fake:
        def __init__(self, srv): pass
        def tools(self): return [{"name": "search_issues", "description": "Search"}, {"name": "create_note", "description": "Write"}]
        def call(self, name, args):
            ran.append(name)
            return {"issues": [{"title": "QA checklist template lives in the wiki"}]}
    monkeypatch.setattr(ms, "_session", lambda srv: Fake(srv))
    ms.add("GitLab", "https://gitlab.example.com/api/mcp", auth="token", token="t")
    ms.save("gitlab", read=["search_issues"], write=["create_note"])
    factory, repo = _sources(tmp, with_repo=False)
    o = ob.Onboarding(factory)
    go(o.study({"projects": ["SCRUM"], "spaces": [], "repo": "", "mcp": ["gitlab"]}))
    last = o.state()["last"]
    assert ran == ["search_issues"], (ran, o.state()["last"]["sources"], o.lines)  # Claude also proposed create_note: never run
    assert last["sources"]["mcp"].startswith("Read 1 result")
    assert "mcp" in calls and "knowledge" in calls
    saved = json.loads((tmp / "company" / "onboarding" / last["id"] / "collected" / "mcp.json").read_text())
    assert "wiki" in saved["results"][0]["text"]


class TwoProjects(MockJira):
    def recent(self, project, limit=200):
        return [dict(t, key=t["key"].replace("SCRUM", project)) for t in super().recent("SCRUM", limit)]


def test_progress_goes_from_0_to_100_and_counts_each_project(home):
    tmp, events, calls = home
    factory = lambda: {"cfg": Config(demo=False, anthropic_api_key="k"), "tracker": TwoProjects(_issues(30)),  # noqa: E731
                       "testrail": None, "confluence": None}
    o = ob.Onboarding(factory)
    assert o.state()["progress"]["percent"] == 0
    go(o.study({"projects": ["SCRUM", "OPTR"], "spaces": [], "repo": ""}))
    pct = [e["percent"] for e in events if e.get("type") == "onboarding" and e.get("event") == "progress" and "percent" in e]
    assert pct and pct == sorted(pct) and pct[-1] == 100                  # only ever goes up, ends at 100
    labels = [e.get("text", "") for e in events if e.get("event") == "progress"]
    assert any("SCRUM" in l for l in labels) and any("OPTR" in l for l in labels)
    assert o.state()["progress"]["percent"] == 100


def test_finishing_merges_what_was_learnt_into_the_general_skills_and_hides_onboarding(home):
    tmp, events, calls = home
    factory, repo = _sources(tmp, with_repo=False)
    o = ob.Onboarding(factory)
    go(o.study({"projects": ["SCRUM", "OPTR"], "spaces": [], "repo": ""}))
    changes = o.state()["last"]["changes"]
    with pytest.raises(ob.OnboardingBusy, match="Keep or undo"):
        go(o.finish())
    gather_optr = next(c for c in changes if c["target"] == "OPTR/gather")
    o.undo(gather_optr["id"])                                             # undone: never merged
    skills.save_project("SCRUM", "jira-comment", "My own SCRUM comment rules", mode="add")   # your edit after the study
    o.keep_all()
    general_before = skills.general("gather")[0]
    calls.clear()
    go(o.finish())
    assert calls.count("polish") == 2                                      # one per step: gather, jira-comment
    gather = skills.general("gather")[0]
    assert gather.startswith(general_before.rstrip()[:200])               # the general skill is kept as it was…
    assert ob.LEARNT_START in gather and "## Polished" in gather          # …with what was learnt added in its own section
    assert skills.project("SCRUM", "gather") is None                      # onboarding's project versions are folded in
    assert "## Polished" in skills.general("jira-comment")[0]
    assert skills.project("SCRUM", "jira-comment")["text"] == "My own SCRUM comment rules"   # your edit stays
    optr = skills.project("OPTR", "gather")
    assert optr is None or optr.get("shipped")
    go_again = skills.general("gather")[0]
    assert go_again.count(ob.LEARNT_START) == 1
    assert config.load_settings()["app"]["onboarding_done"] is True
    st = o.state()
    assert st["last"]["status"] == "finished" and st["finished"] and st["progress"]["percent"] == 100
    with pytest.raises(KeyError):
        o.undo(changes[0]["id"])                                           # finished: no more undo


def test_merging_again_replaces_the_learnt_section():
    once = ob.merge_learnt("# Gather\nGeneral rules.\n", "Learnt A")
    twice = ob.merge_learnt(once, "Learnt B")
    assert twice.startswith("# Gather\nGeneral rules.") and twice.count(ob.LEARNT_START) == 1
    assert "Learnt B" in twice and "Learnt A" not in twice


def test_the_finished_page_explains_what_was_found_and_each_skill_update_can_be_reverted(home):
    tmp, events, calls = home
    factory, repo = _sources(tmp, with_repo=False)
    o = ob.Onboarding(factory)
    go(o.study({"projects": ["SCRUM", "OPTR"], "spaces": [], "repo": ""}))
    o.keep_all()
    before = {s: skills.general(s)[0] for s in ("gather", "jira-comment")}
    go(o.finish())
    last = o.state()["last"]
    assert last["sources"]["tracker"].startswith("Read")                          # what was read
    assert any(c["evidence"] for c in last["changes"])                            # what it was based on
    merged = {m["step"]: m for m in last["finish"]["merged"]}
    assert set(merged) == {"gather", "jira-comment"}
    g = merged["gather"]
    assert g["state"] == "pending" and "## Polished" in g["section"] and g["from"] == ["SCRUM", "OPTR"]
    assert g["name"] == "Gather requirements" and "before" not in g                # the screen gets the change, not whole files

    o.accept_merge("jira-comment")
    assert {m["step"]: m["state"] for m in o.state()["last"]["finish"]["merged"]}["jira-comment"] == "accepted"
    assert o.revert_merge("gather") == "reverted"
    assert skills.general("gather")[0] == before["gather"]                        # the general skill as it was
    assert "## Polished" not in skills.project("SCRUM", "gather")["text"] and not skills.project("SCRUM", "gather").get("shipped")  # project versions are back
    assert skills.project("OPTR", "gather") is not None
    assert {m["step"]: m["state"] for m in o.state()["last"]["finish"]["merged"]}["gather"] == "reverted"
    assert o.revert_merge("gather") == "already reverted"

    skills.save_general("jira-comment", "I rewrote it myself")                     # edited after finishing
    assert o.revert_merge("jira-comment") == "changed since"
    assert skills.general("jira-comment")[0] == "I rewrote it myself"

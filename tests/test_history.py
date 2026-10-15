"""Ticket run records: numbering, results, index, compare, evidence pruning, safe file access."""
from __future__ import annotations

import json

import pytest

from qa_app.workflow import history as H
from qa_app.workflow.models import CheckItem, Env, Section, Ticket


def ticket(results=None, key="SCRUM-8"):
    texts = ["Search ignores letter case", "Empty search shows a hint", "Results load under 2 seconds"]
    results = results or ["nt"] * 3
    t = Ticket(key=key, title="google test 1", type="FE", issue_type="Story",
               env=Env(kind="Test environment", url="https://www.google.com/", source="comment by Andrei"),
               checklist=[Section(name="Search", items=[CheckItem(text=x, result=r) for x, r in zip(texts, results)])])
    return t


def test_run_is_recorded_numbered_and_indexed(tmp_path):
    s = H.RunStore(tmp_path)
    spec = tmp_path / "SCRUM-8.spec.ts"
    spec.write_text("test('[1] x', () => {})")
    t = ticket(["pass", "fail", "nt"])
    r1 = s.start(t, "first", "live", project="SCRUM", account="qa@x", spec_files=[spec], now=1_000_000)
    rec = s.get(r1)
    assert rec["run_no"] == 1 and rec["status"] == "running" and rec["counts"]["nt"] == 3  # nothing shown before it runs
    assert (tmp_path / r1 / "spec" / "SCRUM-8.spec.ts").exists() and rec["spec_hash"]
    s.item_result(r1, 1, "pass")
    assert s.get(r1)["items"][0]["result"] == "pass"
    t.checklist[0].items[1].bug = "Hint missing"
    rec = s.finish(r1, t, exit_code=1, errors={2: "expect(locator).toBeVisible() failed"},
                   attachments={2: [{"kind": "screenshot", "path": "artifacts/x.png"}]},
                   usage=[{"cost": 0.02}, {"cost": 0.01}], now=1_000_042)
    assert rec["status"] == "failed" and rec["duration_s"] == 42 and rec["cost"] == 0.03
    assert rec["items"][1]["error"].startswith("expect") and rec["items"][1]["attachments"][0]["kind"] == "screenshot"
    r2 = s.start(ticket(["pass"] * 3), "rerun_gate2", "live", now=1_000_100)
    s.finish(r2, ticket(["pass"] * 3), now=1_000_130)
    assert s.get(r2)["run_no"] == 2 and s.get(r2)["status"] == "passed"
    assert [r["id"] for r in s.runs_for("SCRUM-8")] == [r1, r2] and s.previous(r2) == r1
    assert [r["id"] for r in s.list(status="passed")] == [r2] and s.list(q="google")[0]["id"] == r2
    # the index can always be rebuilt from the run folders
    s.index_path.write_text("{broken")
    assert {r["id"] for r in s.list()} == {r1, r2}


def test_errors_and_unfinished_runs(tmp_path):
    s = H.RunStore(tmp_path)
    r = s.start(ticket(), "first", "live")
    assert s.fail(r, "npx is not installed")["status"] == "error"
    r2 = s.start(ticket(), "first", "live")
    assert s.close_unfinished() == [r2] and s.get(r2)["status"] == "stopped"


def test_compare_tags_each_check(tmp_path):
    s = H.RunStore(tmp_path)
    a = s.start(ticket(), "first", "live", now=1)
    s.finish(a, ticket(["fail", "pass", "pass"]), now=2)
    t = ticket(["pass", "fail", "pass"])
    t.checklist[0].items[2].text = "Results load under 1 second"  # wording changed → removed + added
    b = s.start(t, "rerun_gate2", "live", now=3)
    s.finish(b, t, now=4)
    d = s.compare(b, a)  # order doesn't matter
    tags = {r["text"]: r["tag"] for r in d["rows"]}
    assert tags == {"Search ignores letter case": "fixed", "Empty search shows a hint": "newly_failing",
                    "Results load under 1 second": "added", "Results load under 2 seconds": "removed"}
    assert d["tally"]["fixed"] == 1 and d["tally"]["newly_failing"] == 1 and not d["env_changed"]
    other = s.start(ticket(key="SCRUM-9"), "first", "live", now=5)
    with pytest.raises(ValueError):
        s.compare(a, other)


def test_evidence_is_pruned_to_the_newest_runs_and_files_stay_inside_the_run(tmp_path):
    s = H.RunStore(tmp_path)
    ids = []
    for n in range(3):
        r = s.start(ticket(), "first", "live", now=10 + n)
        (tmp_path / r / "artifacts").mkdir()
        (tmp_path / r / "artifacts" / "shot.png").write_bytes(b"x" * 10)
        s.finish(r, ticket(["fail", "pass", "pass"]), attachments={1: [{"kind": "screenshot", "path": "artifacts/shot.png"}]}, now=20 + n)
        ids.append(r)
    assert s.evidence_bytes() == 30
    assert s.prune_evidence("SCRUM-8", keep=2) == [ids[0]]
    old = s.get(ids[0])
    assert not old["evidence_kept"] and old["items"][0]["attachments"] == [] and old["items"][0]["result"] == "fail"
    assert s.file(ids[2], "artifacts/shot.png").name == "shot.png"
    for bad in ("../" + ids[1] + "/run.json", "/etc/passwd", "artifacts/missing.png"):
        with pytest.raises(KeyError):
            s.file(ids[2], bad)
    with pytest.raises(KeyError):
        s.dir("../x")

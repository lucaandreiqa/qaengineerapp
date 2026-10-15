"""Reports from History: trends, run / ticket / period reports, CSV, sending."""
from __future__ import annotations

import csv
import io

import pytest

from qa_app.workflow import history as H
from qa_app.workflow import reports as R
from tests.test_history import ticket


def seeded(tmp_path):
    s = H.RunStore(tmp_path)
    ids = {}
    # SCRUM-8: fail → pass (same env and spec) ; SCRUM-9: pass first time ; SCRUM-7: flaky check
    a = s.start(ticket(), "first", "live", project="SCRUM", now=1_000_000); s.finish(a, ticket(["fail", "pass", "pass"]), now=1_000_030)
    b = s.start(ticket(), "rerun_gate2", "live", project="SCRUM", now=1_086_400); s.finish(b, ticket(["pass"] * 3), now=1_086_420)
    c = s.start(ticket(key="SCRUM-9"), "first", "live", project="SCRUM", now=1_086_500); s.finish(c, ticket(["pass"] * 3, key="SCRUM-9"), now=1_086_510)
    for n, res in enumerate([["pass", "pass", "pass"], ["pass", "fail", "pass"], ["pass", "pass", "pass"]]):
        r = s.start(ticket(key="SCRUM-7"), "first" if not n else "redo", "live", project="SCRUM", now=1_100_000 + n * 100)
        s.finish(r, ticket(res, key="SCRUM-7"), now=1_100_050 + n * 100)
    s.annotate(b, comment="QA result: 3/3 checks pass.", moved_to="Done")
    ids.update(a=a, b=b, c=c)
    return s, ids


def test_trends_pass_rate_first_time_and_flaky(tmp_path):
    s, _ = seeded(tmp_path)
    t = R.trends(s)
    assert t["runs"] == 6 and t["tickets"] == 3 and t["pass_rate"] == round(100 * 4 / 6)
    assert t["first_time_pass"] == round(100 * 2 / 3) and t["avg_runs_to_green"] == round((2 + 1 + 1) / 3, 1)
    assert [(f["key"], f["text"], f["flips"]) for f in t["flaky"]] == [("SCRUM-7", "Empty search shows a hint", 2)]
    assert t["by_project"][0] == {"name": "SCRUM", "runs": 6, "pass_rate": 67, "tickets": 3}
    assert sum(d["runs"] for d in t["series"]) == 6
    assert {x["key"] for x in t["per_ticket"]} == {"SCRUM-7", "SCRUM-8", "SCRUM-9"}


def test_reports_are_self_contained_and_saved(tmp_path):
    s, ids = seeded(tmp_path)
    shot = tmp_path / ids["a"] / "artifacts" / "s.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"\x89PNG fake")
    rec = s.get(ids["a"]); rec["items"][0]["attachments"] = [{"kind": "screenshot", "path": "artifacts/s.png"}]; rec["items"][0]["error"] = "boom"
    s._put(rec)
    rs = R.ReportStore(s)
    m = rs.create("run", ids["a"])
    page = rs.html_path(m["id"]).read_text()
    assert m["kind"] == "run" and m["key"] == "SCRUM-8" and "data:image/png;base64," in page and "boom" in page and "<script" not in page
    assert "Search ignores letter case" in page and "1/3" not in page and "Failed" in page
    t = rs.create("ticket", "SCRUM-8")
    tp = rs.html_path(t["id"]).read_text()
    assert "Green at" in tp and "run 2" in tp and "QA result: 3/3 checks pass." in tp and "Moved to <b>Done</b>" in tp
    p = rs.create("period", since=None, label="all time")
    pp = rs.html_path(p["id"]).read_text()
    assert "Tickets tested" in pp and "SCRUM-7" in pp and "Flaky checks" in pp
    assert [x["kind"] for x in rs.list()] == ["period", "ticket", "run"]
    assert "*SCRUM-8" in m["summary"] and "✗ Search ignores letter case" in m["summary"]
    with pytest.raises(KeyError):
        rs.get("../x")


def test_csv_exports(tmp_path):
    s, _ = seeded(tmp_path)
    rows = list(csv.reader(io.StringIO(R.runs_csv(s, s.list()))))
    assert rows[0][:3] == ["run_id", "ticket", "title"] and len(rows) == 7
    checks = list(csv.reader(io.StringIO(R.checks_csv(s, s.list()))))
    assert checks[0][5:7] == ["text", "result"] and len(checks) == 1 + 6 * 3


def test_send_previews_and_posts(tmp_path):
    s, ids = seeded(tmp_path)
    rs = R.ReportStore(s)
    m = rs.create("run", ids["a"])
    with pytest.raises(R.SendError, match="Slack isn't set up"):
        R.preview(m, "slack", {})
    posted = []

    class Http:
        def post(self, url, json=None, timeout=None, **kw):
            posted.append((url, json))

            class Ok:
                def raise_for_status(self):
                    pass
            return Ok()

    settings = {"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/x"}, "teams": {"enabled": True, "webhook_url": "https://t/x"},
                "jira": {"auth": "mcp", "cloud_id": "c1", "base_url": "https://q.atlassian.net"}}
    assert R.preview(m, "slack", settings)["text"] == m["summary"]
    assert R.send(rs, m["id"], "slack", settings, http=Http()) == "Posted to Slack" and posted[0][1]["text"] == m["summary"]
    assert R.send(rs, m["id"], "teams", settings, http=Http()) == "Posted to Microsoft Teams"
    assert posted[1][1]["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"
    pv = R.preview(m, "tracker", settings)
    assert pv["to"] == "jira" and "comment" in pv["what"]  # Atlassian sign-in: summary as a comment
    period = rs.create("period", label="x")
    with pytest.raises(R.SendError, match="belong to a ticket"):
        R.preview(period, "tracker", settings)

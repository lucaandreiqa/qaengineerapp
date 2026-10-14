"""Demo data for the board: sample OPTR tickets at the states the design shows. Only used in demo mode."""
from __future__ import annotations

from .models import (DEFAULT_BE_COMPONENTS, DEFAULT_FE_COMPONENTS, CheckItem, CleanupItem, DraftCase, Env, Section,
                     Ticket, classify_type, component_list, status_category, type_label)

STAGING = Env(kind="shared staging · ticket is merged", url="https://staging.shop-demo.test/", source="settings",
          api="Default environment from settings: confirm before changing sensitive settings", shared=True)

# key, title, components (Jira), status, stage, sub, extras, checklist[(section, [(text, result, bug)])], cleanup, left
_T = [
    dict(key="OPTR-48512", issue_type="Story", priority="Medium", title="Worked hours report export to CSV", components=["Frontend", "Backend"], status="Open", stage=0, sub="working", p1=1,
         env=Env(kind="Test environment", url="https://feature-48512.preview.shop-demo.test/", api="API: https://api.staging.shop-demo.test/", source="comment by Developer"),
         doing="Reading commits on shop-admin PR #9214",
         check=[("Export", [("Export button appears on the Worked hours report", "pass"), ("CSV has one row per employee per day", "pass"), ("CSV columns follow the on-screen order", "partial")]),
                ("Permissions", [("Export is hidden without the export permission", "pass")])],
         cleanup=[("WorkedHoursExportEnabled", "false")]),
    dict(key="OPTR-48507", issue_type="Task", priority="Low", title="Stock mutation reasons configurable per store", components=["Backend"], status="Open", stage=0, sub="blocked", p1=1, env=None,
         check=[("Configuration", [("Reasons can be created per store", "pass"), ("Child stores inherit the parent reasons", "pass")]),
                ("Stock mutations", [("A mutation without a reason is rejected when reasons are required", "pass")])],
         cleanup=[("StockMutationReasonsRequired", "false")]),
    dict(key="OPTR-48498", issue_type="Bug", priority="High", title="Device list filter by station", components=["Frontend"], status="Merged", stage=0, sub="gate", env=STAGING,
         check=[("Filter", [("Station filter lists every station in the selected store", "pass"), ("Filtering updates the device count", "pass"),
                            ("Filter is kept in the URL", "fail", "Reload drops ?station= and shows all devices. UI writes the param with replaceState only after the first change. Severity: Minor")]),
                ("Empty states", [("A station without devices shows the empty state", "pass"), ("Clearing the filter restores all devices", "pass")])]),
    dict(key="OPTR-48490", issue_type="Story", priority="High", title="Discount usage limit per customer", components=["Backend"], status="Merged", stage=1, sub="working", serial=True, env=STAGING,
         doing="Building OPTR-48490.spec.ts and .serial.spec.ts",
         check=[("Usage limit", [("Discount applies until the per-customer limit is reached", "pass"), ("The next order over the limit gets no discount", "pass"), ("The limit counts per customer, not per device", "pass")]),
                ("Concurrency", [("Two parallel orders cannot both use the last allowance", "blocked", "Second session could not start: the shared staging store has one cash drawer. Needs a second drawer to unblock.")])],
         cleanup=[("DiscountUsageCheckEnabled", "true")], left="2 orders (orders cannot be deleted), prefixed OPTR-48490"),
    dict(key="OPTR-48471", issue_type="Story", priority="Highest", title="Cashier PIN reset from the admin app", components=["Frontend"], status="Open", stage=2, sub="sso", needs_sso=True,
         env=Env(kind="Test environment", url="https://pr-48471.preview.shop-demo.test/", api="API: https://api.pr-48471.preview.shop-demo.test/", source="comment by Developer"),
         check=[("PIN reset", [("Reset PIN shows for users with the permission", "pass"), ("The new PIN is shown once and can be copied", "pass"), ("The old PIN stops working right after the reset", "pass")]),
                ("Audit", [("The reset is written to the user audit log", "partial")])],
         cleanup=[("UserPinLength", "4")], left="1 minted PIN (PINs cannot be deleted), prefixed OPTR-48471"),
    dict(key="OPTR-48466", issue_type="Bug", priority="High", title="Order search by external reference", components=["Frontend", "Backend"], status="Open", stage=2, sub="gate",
         env=Env(kind="Test environment", url="https://feature-optr-48466.shop-admin.pages.dev/", api="API: the staging API, seen in the network requests", source="comment by Developer"),
         check=[("Search", [("An exact external reference finds the order", "pass"), ("A partial reference matches from the start", "pass"), ("Search ignores letter case", "pass"),
                            ("Leading and trailing spaces are trimmed", "fail", 'Searching " EXT-1042 " returns 0 orders; the UI sends the value untrimmed to SearchOrders. Severity: Major')]),
                ("Results", [("A result row opens the order detail", "pass"), ("Orders from other stores are not returned", "pass"), ("Results arrive in under 2 s with 10k+ orders", "partial"), ("Export of filtered results", "nt")])],
         cleanup=[("OrderSearchIncludeExternalRef", "false"), ("OrderSearchMaxResults", "50")], left="3 orders (orders cannot be deleted), prefixed OPTR-48466"),
    dict(key="OPTR-48455", issue_type="Task", priority="Medium", title="Worked hours settings per store", components=["Core"], status="Open", stage=3, sub="comment", target="Docs",
         env=Env(kind="Test environment", url="https://pr-9031.preview.shop-demo.test/", api="API: same site", source="comment by Developer"),
         check=[("Settings", [("The setting can be set for a country", "pass"), ("Stores inherit the country value", "pass"), ("A store override wins over the parent", "pass")]),
                ("Read service", [("GetWorkedHours rounds hours per the setting", "pass"), ("An invalid rounding value is rejected", "pass")])],
         cleanup=[("WorkedHoursRounding", "15")]),
    dict(key="OPTR-48449", issue_type="Story", priority="Low", title="Receipt footer text per store", components=["Frontend"], status="Merged", stage=3, sub="transition", comment_at="13:21", env=STAGING,
         check=[("Footer text", [("Footer text saves per store", "pass"), ("Line breaks are kept on the printed receipt", "pass"), ("Text over 200 characters is rejected", "pass")])],
         cleanup=[("ReceiptFooterText", "(empty)")]),
    dict(key="OPTR-48437", issue_type="Story", priority="High", title="Gift card balance check endpoint", components=["Backend"], status="Merged", stage=4, sub="gate", section="Finance › Gift cards", dups=1, env=STAGING,
         check=[("Balance", [("A valid card returns its current balance", "pass"), ("An expired card returns an expired error", "pass"), ("An unknown card returns not found", "pass")]),
                ("Security", [("The endpoint requires the gift card view permission", "pass"), ("Rate limit applies after 10 calls per minute", "pass"), ("The balance is masked in logs", "partial")])]),
    dict(key="OPTR-48430", issue_type="Task", priority="Medium", title="Bulk copy of store settings", components=["Frontend"], status="Merged", stage=4, sub="approved", section="Stores › Settings", dups=0, env=STAGING,
         check=[("Copy", [("Selected settings copy to every chosen store", "pass"), ("Existing values are only overwritten after confirming", "pass"), ("The summary lists each store and setting", "pass")])],
         cleanup=[("StoreSettingsBulkCopyEnabled", "false")]),
]

LATE = dict(key="OPTR-48520", issue_type="Story", priority="Medium", title="Shift planner shows break times", components=["Frontend"], status="Testing", stage=0, sub="working", p1=0,
            env=Env(kind="Test environment", url="https://feature-48520.preview.shop-demo.test/", api="API: https://api.staging.shop-demo.test/", source="comment by Developer"),
            doing="Gathering context from Jira",
            check=[("Breaks", [("Break blocks show on the shift", "pass"), ("Break length matches the shift template", "pass")])])


def _type(components: list[str]) -> str:
    return classify_type(components, component_list(DEFAULT_FE_COMPONENTS), component_list(DEFAULT_BE_COMPONENTS))


def _ticket(d: dict) -> Ticket:
    ran = d["stage"] > 2 or (d["stage"] == 2 and d["sub"] == "gate")
    sections, mock = [], []
    for name, items in d["check"]:
        sec = Section(name=name)
        for it in items:
            text, res, bug = it[0], it[1], (it[2] if len(it) > 2 else "")
            mock.append([res, bug])
            sev = ("Major" if "Major" in bug else "Minor") if res == "fail" else None
            sec.items.append(CheckItem(text=text, result=res if ran else "nt", bug=bug if ran else "", severity=sev if ran else None))
        sections.append(sec)
    cleanup = [CleanupItem(name=n, value=v) for n, v in d.get("cleanup", [])]
    passed = [i for s in sections for i in s.items if i.result == "pass"]
    t = Ticket(
        key=d["key"], title=d["title"], type=_type(d["components"]), components=d["components"], status=d["status"], stage=d["stage"], sub=d["sub"],
        env=d.get("env"), p1=d.get("p1", 0), doing=d.get("doing", ""), checklist=sections, ran=ran,
        cleanup=cleanup if ran else [], left=d.get("left", "") if ran else "", serial=d.get("serial", False),
        needs_sso=d.get("needs_sso", False), target=d.get("target", ""), comment_at=d.get("comment_at", ""),
        section=d.get("section", ""), dups=d.get("dups", 0), mock_results=mock,
        mock_cleanup=cleanup, mock_left=d.get("left", ""),
    )
    t.issue_type, t.priority, t.status_cat = d["issue_type"], d["priority"], status_category(d["status"])
    t.usage = _demo_usage(d, ran)
    t.context = _demo_context(d)
    if d["stage"] == 4 and d["sub"] != "drafting":
        existing = {"An unknown card returns not found"} if d.get("dups") else set()  # already in the mock TestRail section
        t.cases = [DraftCase(title=i.text) for i in passed if i.text not in existing]
    if d["stage"] == 3 and d["sub"] == "transition":
        t.transitions = ["Docs", "Ready to merge", "Done", "Reopened"]
    return t


def _demo_usage(d: dict, ran: bool) -> list[dict]:
    """Sample Claude usage for the demo: one call per step the ticket has been through (Sonnet 5.5 prices)."""
    from .costs import entry

    calls = []
    st, sub = d["stage"], d["sub"]
    n = sum(len(items) for _, items in d["check"])
    if st > 0 or sub == "gate":
        calls.append(("gather", 7000 + 900 * n, 900 + 160 * n))
    if st > 1 or (st == 1 and sub != "working"):
        calls.append(("create-tests", 5200 + 400 * n, 3600 + 520 * n))
    if ran and any(r[1] in ("fail", "partial", "blocked") for _, items in d["check"] for r in items):
        calls.append(("run-tests", 3100 + 200 * n, 650))
    if st >= 3:
        calls.append(("jira-comment", 2900 + 150 * n, 520 + 40 * n))
    if st == 4 and sub != "drafting":
        calls.append(("testrail", 2600 + 160 * n, 1300 + 210 * n))
    base = 1791990000.0
    return [entry(step, "claude-sonnet-5-5", {"input_tokens": i, "output_tokens": o}, at=base + k * 600) for k, (step, i, o) in enumerate(calls)]


def _demo_context(d: dict) -> dict:
    """A plausible 'what the ticket says' for the demo drawer."""
    from .ticket_context import build, summary

    area = d["check"][0][0]
    raw = {"key": d["key"], "fields": {
        "summary": d["title"], "status": {"name": d["status"]}, "issuetype": {"name": d["issue_type"]},
        "priority": {"name": d["priority"]},
        "labels": [area.lower().replace(" ", "-"), "release-2026.11"], "fixVersions": [{"name": "2026.11"}],
        "reporter": {"displayName": "Product Owner"}, "assignee": {"displayName": "Developer"},
        "description": f"{d['title']}.\n\n" + "\n".join(f"- {i[0]}" for _, items in d["check"] for i in items[:2]),
        "components": [{"name": c} for c in d["components"]],
        "comment": {"comments": [{"body": "Ready for QA.", "author": {"displayName": "Developer"}}]}}}
    return summary(build(raw))


def seed_tickets() -> list[Ticket]:
    return [_ticket(d) for d in _T]


def late_ticket() -> Ticket:
    return _ticket(LATE)


def jira_issues() -> tuple[list[dict], list[dict]]:
    """Issue records for MockJira. Comments drive environment resolution."""
    def rec(d: dict) -> dict:
        env = d.get("env")
        comments = ["Moved to Testing."]
        if env is not None and not env.shared:  # how teams usually share it: a comment with the link
            comments.append(f"Deployed to the preview environment: {env.url}")
        return {"key": d["key"], "title": d["title"], "status": d["status"], "components": d["components"],
                "issue_type": d["issue_type"], "priority": d["priority"],
                "merged": d["status"] == "Merged", "comments": comments,
                "description": f"{d['title']}. See the linked PR for details."}
    return [rec(d) for d in _T], [rec(LATE)]


def write_seed_files(cfg, tickets: list[Ticket]) -> None:
    """Write the tests/tickets/<KEY>/ files a seeded ticket would already have at its stage."""
    from . import agent

    for t in tickets:
        has_plan = t.stage > 0 or t.sub == "gate"
        if t.stage > 0 or t.p1 > 0 or t.sub == "gate":
            agent.write_file(cfg, t.key, f"{t.key}-context.md", f"# {t.key}: {t.title}\n\n- Status: {t.status}\n- Type: {type_label(t.type)} (components: {', '.join(t.components)})\n")
        if has_plan:
            agent.write_file(cfg, t.key, f"{t.key}-scenarios.md", f"# {t.key} scenarios\n\n" + "\n".join(f"- Scenario: {i.text}" for i in t.items()) + "\n")
            agent.write_file(cfg, t.key, f"{t.key}-qa-checklist.md", agent.checklist_md(t))
        if t.stage > 1:
            agent.write_file(cfg, t.key, f"{t.key}.spec.ts", agent.spec_template(t, cfg))
            if t.serial:
                agent.write_file(cfg, t.key, f"{t.key}.serial.spec.ts", agent.spec_template(t, cfg, serial=True))
        if t.ran:
            agent.write_file(cfg, t.key, f"{t.key}-report.md", agent.report_md(t, cfg))
        if t.stage == 4 and t.sub != "drafting":
            agent.write_file(cfg, t.key, f"{t.key}-testrail-cases.md", agent.cases_md(t))

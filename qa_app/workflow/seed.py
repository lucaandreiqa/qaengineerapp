"""Demo data for the board: sample OPTR tickets at the states the design shows. Only used in demo mode."""
from __future__ import annotations

from .models import CheckItem, CleanupItem, DraftCase, Env, Section, Ticket

EUW = Env(kind="Shared euw · ticket is merged", url=".env defaults (euw)",
          api="Shared environment rules: confirm before changing sensitive settings", shared=True)

# key, title, comp, status, stage, sub, extras, checklist[(section, [(text, result, bug)])], cleanup, left
_T = [
    dict(key="OPTR-48512", title="Worked hours report export to CSV", comp="Frontend", status="Open", stage=0, sub="working", p1=1,
         env=Env(kind="Frontend preview", url="https://feature-optr-48512--euw.newblack.test.eva-online.cloud/", api="API: shared api.euw.newblack.test.eva-online.cloud"),
         doing="Reading commits on new-black/eva-suite-admin PR #9214",
         check=[("Export", [("Export button appears on the Worked hours report", "pass"), ("CSV has one row per employee per day", "pass"), ("CSV columns follow the on-screen order", "partial")]),
                ("Permissions", [("Export is hidden without the export permission", "pass")])],
         cleanup=[("WorkedHoursExportEnabled", "false")]),
    dict(key="OPTR-48507", title="Stock mutation reasons configurable per OU", comp="Core", status="Open", stage=0, sub="blocked", p1=1, env=None,
         check=[("Configuration", [("Reasons can be created per OU", "pass"), ("Child OUs inherit the parent reasons", "pass")]),
                ("Stock mutations", [("A mutation without a reason is rejected when reasons are required", "pass")])],
         cleanup=[("StockMutationReasonsRequired", "false")]),
    dict(key="OPTR-48498", title="Device list filter by station", comp="Frontend", status="Merged", stage=0, sub="gate", env=EUW,
         check=[("Filter", [("Station filter lists every station in the selected OU", "pass"), ("Filtering updates the device count", "pass"),
                            ("Filter is kept in the URL", "fail", "Reload drops ?station= and shows all devices. UI writes the param with replaceState only after the first change. Severity: Minor")]),
                ("Empty states", [("A station without devices shows the empty state", "pass"), ("Clearing the filter restores all devices", "pass")])]),
    dict(key="OPTR-48490", title="Discount usage limit per customer", comp="Core", status="Merged", stage=1, sub="working", serial=True, env=EUW,
         doing="Building OPTR-48490.spec.ts and .serial.spec.ts",
         check=[("Usage limit", [("Discount applies until the per-customer limit is reached", "pass"), ("The next order over the limit gets no discount", "pass"), ("The limit counts per customer, not per device", "pass")]),
                ("Concurrency", [("Two parallel orders cannot both use the last allowance", "blocked", "Second session could not start: the shared euw OU has one cash drawer. Needs a second drawer to unblock.")])],
         cleanup=[("DiscountUsageCheckEnabled", "true")], left="2 orders (orders cannot be deleted), prefixed OPTR-48490"),
    dict(key="OPTR-48471", title="Cashier PIN reset from Admin Suite", comp="Frontend", status="Open", stage=2, sub="sso", needs_sso=True,
         env=Env(kind="Frontend preview", url="https://optr-48471--7f3a9c.on-eva.io", api="API: api.optr-48471.ci-cd.on-eva.io"),
         check=[("PIN reset", [("Reset PIN shows for users with the permission", "pass"), ("The new PIN is shown once and can be copied", "pass"), ("The old PIN stops working right after the reset", "pass")]),
                ("Audit", [("The reset is written to the user audit log", "partial")])],
         cleanup=[("UserPinLength", "4")], left="1 minted PIN (PINs cannot be deleted), prefixed OPTR-48471"),
    dict(key="OPTR-48466", title="Order search by external reference", comp="Frontend", status="Open", stage=2, sub="gate",
         env=Env(kind="Cloudflare Pages preview", url="https://feature-optr-48466.eva-suite-admin.pages.dev/", api="API: shared euw, confirmed from network requests"),
         check=[("Search", [("An exact external reference finds the order", "pass"), ("A partial reference matches from the start", "pass"), ("Search ignores letter case", "pass"),
                            ("Leading and trailing spaces are trimmed", "fail", 'Searching " EXT-1042 " returns 0 orders; the UI sends the value untrimmed to SearchOrders. Severity: Major')]),
                ("Results", [("A result row opens the order detail", "pass"), ("Orders from other OUs are not returned", "pass"), ("Results arrive in under 2 s with 10k+ orders", "partial"), ("Export of filtered results", "nt")])],
         cleanup=[("OrderSearchIncludeExternalRef", "false"), ("OrderSearchMaxResults", "50")], left="3 orders (orders cannot be deleted), prefixed OPTR-48466"),
    dict(key="OPTR-48455", title="Worked hours settings per OU", comp="Core", status="Open", stage=3, sub="comment", target="Docs",
         env=Env(kind="PR environment", url="https://pr-9031.ci-cd.on-eva.io/", api="Found in the ticket comments"),
         check=[("Settings", [("The setting can be set on a country OU", "pass"), ("Store OUs inherit the country value", "pass"), ("A store override wins over the parent", "pass")]),
                ("Read service", [("GetWorkedHours rounds hours per the setting", "pass"), ("An invalid rounding value is rejected", "pass")])],
         cleanup=[("WorkedHoursRounding", "15")]),
    dict(key="OPTR-48449", title="Receipt footer text per store", comp="Frontend", status="Merged", stage=3, sub="transition", comment_at="13:21", env=EUW,
         check=[("Footer text", [("Footer text saves per store", "pass"), ("Line breaks are kept on the printed receipt", "pass"), ("Text over 200 characters is rejected", "pass")])],
         cleanup=[("ReceiptFooterText", "(empty)")]),
    dict(key="OPTR-48437", title="Gift card balance check endpoint", comp="Core", status="Merged", stage=4, sub="gate", section="Finance › Gift cards", dups=1, env=EUW,
         check=[("Balance", [("A valid card returns its current balance", "pass"), ("An expired card returns an expired error", "pass"), ("An unknown card returns not found", "pass")]),
                ("Security", [("The endpoint requires the gift card view permission", "pass"), ("Rate limit applies after 10 calls per minute", "pass"), ("The balance is masked in logs", "partial")])]),
    dict(key="OPTR-48430", title="Bulk copy of OU settings", comp="Frontend", status="Merged", stage=4, sub="approved", section="Organization units › Settings", dups=0, env=EUW,
         check=[("Copy", [("Selected settings copy to every chosen OU", "pass"), ("Existing values are only overwritten after confirming", "pass"), ("The summary lists each OU and setting", "pass")])],
         cleanup=[("OuSettingsBulkCopyEnabled", "false")]),
]

LATE = dict(key="OPTR-48520", title="Shift planner shows break times", comp="Frontend", status="Testing", stage=0, sub="working", p1=0,
            env=Env(kind="Frontend preview", url="https://feature-optr-48520--euw.newblack.test.eva-online.cloud/", api="API: shared api.euw.newblack.test.eva-online.cloud"),
            doing="Gathering context from Jira",
            check=[("Breaks", [("Break blocks show on the shift", "pass"), ("Break length matches the shift template", "pass")])])


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
        key=d["key"], title=d["title"], comp=d["comp"], status=d["status"], stage=d["stage"], sub=d["sub"],
        env=d.get("env"), p1=d.get("p1", 0), doing=d.get("doing", ""), checklist=sections, ran=ran,
        cleanup=cleanup if ran else [], left=d.get("left", "") if ran else "", serial=d.get("serial", False),
        needs_sso=d.get("needs_sso", False), target=d.get("target", ""), comment_at=d.get("comment_at", ""),
        section=d.get("section", ""), dups=d.get("dups", 0), mock_results=mock,
        mock_cleanup=cleanup, mock_left=d.get("left", ""),
    )
    if d["stage"] == 4 and d["sub"] != "drafting":
        existing = {"An unknown card returns not found"} if d.get("dups") else set()  # already in the mock TestRail section
        t.cases = [DraftCase(title=i.text) for i in passed if i.text not in existing]
    if d["stage"] == 3 and d["sub"] == "transition":
        t.transitions = ["Docs", "Ready to merge", "Done", "Reopened"]
    return t


def seed_tickets() -> list[Ticket]:
    return [_ticket(d) for d in _T]


def late_ticket() -> Ticket:
    return _ticket(LATE)


def jira_issues() -> tuple[list[dict], list[dict]]:
    """Issue records for MockJira. Comments drive environment resolution."""
    def rec(d: dict) -> dict:
        env = d.get("env")
        comments = []
        if env is not None and env.kind == "PR environment":
            comments.append(f"PR environment is up: {env.url}")
        preview = env.url if env is not None and "preview" in env.kind.lower() else ""
        return {"key": d["key"], "title": d["title"], "status": d["status"], "comp": d["comp"],
                "merged": d["status"] == "Merged", "preview_url": preview, "comments": comments,
                "description": f"{d['title']}. See the linked PR for details."}
    return [rec(d) for d in _T], [rec(LATE)]


def write_seed_files(cfg, tickets: list[Ticket]) -> None:
    """Write the tests/tickets/<KEY>/ files a seeded ticket would already have at its stage."""
    from . import agent

    for t in tickets:
        has_plan = t.stage > 0 or t.sub == "gate"
        if t.stage > 0 or t.p1 > 0 or t.sub == "gate":
            agent.write_file(cfg, t.key, f"{t.key}-context.md", f"# {t.key}: {t.title}\n\n- Status: {t.status}\n- Component: {t.comp}\n")
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

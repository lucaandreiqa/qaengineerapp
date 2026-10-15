# History, live ticket view and Reports: design

Date: 2026-10-15 · Status: approved in conversation, awaiting written-spec review

## 1. Intent

YourQA's **Run** and **History** screens today serve the old site crawler (crawl a URL for broken pages, visual changes,
accessibility, SEO, performance). The Testing board's own ticket runs (generated Playwright specs) appear nowhere:
each run overwrites the previous one, results arrive only when Playwright exits, and no evidence is kept.

The user wants:

- **History** = every ticket test run, its evidence, and comparison between runs of a ticket.
- **Reports** (replacing the Run screen) = trends plus generated reports (per run, per ticket, per period) with export
  and send.
- In the **open ticket**: live, plain-language updates on where the ticket is and what is happening, and a friendly
  QA checklist with clear passes and fails.
- The site crawler removed.

What the user said: ticket test runs are the purpose; remove the Run section, keep History; History needs all of
run list, evidence, compare, trends; it also needs reporting: per run, per ticket, period summary, send/export;
"run needs to be renamed to reports"; Claude keeps the user posted in the open ticket; a friendly checklist with checks
and fails.

Assumptions made (approved with the design): storage as files on disk (not inside tickets, not SQLite); routine live
updates come from app milestones, Claude writes only step summaries; evidence for failures only by default.

**Success looks like:** after a ticket runs, the user can open History, see every run of it, open any run's evidence,
compare two runs, and produce a PDF report to attach to Jira or a summary to post in Slack, without leaving YourQA;
while a ticket runs, the open ticket shows each check turning green or red as it happens.

## 2. Navigation

Sidebar: **Board · History · Reports · Integrations · Skills** (⌘1–5). The web app's Run screen and site-check
form, `qa_app/web/runs.py`, the `/api/runs*` routes and the "Run site checks on this environment" button are removed.
`#/run…` links route to History. The old `runs/` folder on disk is left untouched and no longer read by the web app.

The crawler itself (`qa_app/runner.py`, `qa_app/checks/*`, `qa_app/report.py`) **stays**: the command-line tool used
by the CI pipeline files in `ci/` and the classic desktop window (`run_classic.command`) depend on it. They are not
changed by this work. Removing them is a separate decision.

## 3. Run records and storage

**A run** is one execution of a ticket's Playwright spec(s): first run in step 2, rerun at Gate 2, rerun suggested in
the chat, or a run after an environment change. Runs are numbered per ticket and record their trigger:
`first` · `rerun_gate2` · `rerun_chat` · `after_env_change`.

**Location:** `<app folder>/history/live/` and `<app folder>/history/demo/` (demo runs only listed while demo data
is on). One folder per run, id `<KEY>-<YYYYMMDD-HHMMSS>`:

```
history/live/SCRUM-8-20261015-065412/
  run.json            full record (below)
  playwright.config.ts  generated for this run (§5)
  events.jsonl        live reporter output (§4)
  results.json        Playwright JSON report
  report/             Playwright HTML report
  artifacts/          screenshots, videos, traces
  spec/               copies of the spec files that ran
history/live/index.json   one summary line per run
```

**run.json:** id, key, title, project, type (FE/BE/FE+BE), issue_type, run number, trigger, mode (live/demo),
environment (url, kind, source), test account and scope, started, finished, duration_s, status
(`passed` · `failed` · `error` · `stopped`), error message (for `error`), Playwright exit code, checklist snapshot
(sections → items: text, result, bug, severity, error detail, attachments [kind, path]), cleanup items, skill
versions, Claude usage entries within the run window and their cost, spec hashes.

**index.json line:** id, key, title, project, type, issue_type, run_no, trigger, mode, env host, started,
duration_s, status, counts {pass, partial, fail, blocked, nt}, evidence_kept (bool).

**Status rule:** `passed` when no item is fail/blocked/nt; `failed` when any is fail/partial/blocked; `error` when
the run could not start or Playwright produced no report; `stopped` when cancelled.

**Module:** `qa_app/workflow/history.py`, `RunStore(root)`:
`start(ticket, trigger) -> run_id`, `event(run_id, ev)`, `finish(run_id, ticket, results, cleanup, exit_code)`,
`fail(run_id, message)`, `list(filters) -> [summary]`, `get(run_id) -> record`, `runs_for(key)`,
`compare(a, b) -> diff`, `prune_evidence(key, keep)`. Writes are atomic (temp file + rename); the index is rebuilt from
run folders if missing or corrupt. The engine's `_run` calls `start` before Playwright and `finish`/`fail` after;
demo runs go through the same calls with simulated results.

## 4. Open ticket: live updates and the friendly checklist

**Live feed.** The chat pane also carries progress. New message role `progress` (small, timeline style) posted on
milestones:

- step 1: ticket read (comments, description, links counted), environment found or needed, checklist written (N
  checks in M sections);
- step 2: spec built, run started on <env>, each check started / finished ("Check 3 of 6: Search ignores letter case
  · passed"), run finished with counts;
- gates reached, comment posted, ticket moved, TestRail draft ready, errors.

Each finished step's progress lines fold into one expandable line. **Claude summaries** (role `assistant`) are added
at two points only: after step 1 (what it will test and why) and after a run (why checks failed: reuses the existing
result-review call, no extra Claude call). Routine progress lines never call Claude.

**Per-check progress.** A small Playwright reporter (`yourqa-reporter.js`, written into the run folder) appends JSONL
events: `begin {index,title}`, `end {index,title,status,duration,error,attachments}`, `done {status}`. The engine
starts Playwright without waiting on `communicate()`, tails `events.jsonl` every 0.5 s, maps each test to its
checklist item (by the index the spec uses, falling back to normalised title), updates the ticket's item
`running/result` and posts the progress line. Ticket field `running_item: int` (−1 when idle).

**Friendly checklist** (ticket details and History run page share one component):

- header: counts ✓ passed · ✗ failed · ◐ partial · ⊘ blocked · ○ not tested, overall progress bar, filter
  All / Failed / Passed;
- one card per section with "5/6 passed";
- one row per check: icon and colour (green ✓, red ✗, amber ◐, grey ⊘, hollow ○), spinner on the running check;
- failed / partial / blocked rows expand: plain-language note, error text, screenshot thumbnail, video, trace,
  **Ask Claude about this** (opens the chat with "About check N: <text>" prefilled and the item referenced);
- before any run every item shows "not tested"; a result is never shown before a real run.

## 5. Evidence capture

Per run YourQA generates `playwright.config.ts` in the run folder and runs
`npx playwright test --config <run>/playwright.config.ts <specs>` from the workspace:

- `use.baseURL` = environment URL; `use.storageState` = saved SSO session when present (fixes generated specs not
  using the session);
- `screenshot: 'only-on-failure'` (or `'on'` when the board setting *Evidence: every check* is on),
  `video: 'retain-on-failure'`, `trace: 'retain-on-failure'`;
- `outputDir: <run>/artifacts`; reporters: `yourqa-reporter.js`, `json` (→ `results.json`), `html`
  (→ `report/`, `open: 'never'`).

Attachments per test map to their checklist item. Viewing: screenshots as thumbnails with a full-size view; video
inline (`<video>`); trace via **Open in Trace Viewer** (server runs `npx playwright show-trace <file>` on the user's
machine) and download; **Full report** opens `report/index.html` served from the run folder.

**Retention:** run.json and index lines are kept forever. Evidence (`artifacts/`, `report/`, videos, traces) is kept
for the last *N* runs per ticket (setting on the Testing board card, default 5); older runs get `evidence_kept=false`
and show "evidence removed". History shows the total evidence size.

New Testing board settings: `evidence_every_check` (bool, default false), `evidence_keep_runs` (int, default 5).

## 6. History screen

Route `#/history`, run page `#/history/<run_id>`, compare `#/history/<run_id>?vs=<other_id>`.

**List:** filters (search key/title, project, FE/BE, status, environment, date: today / 7 days / 30 days / all),
summary strip (runs, pass rate, tickets failing now), rows grouped by day: key and title, "run n", trigger label,
environment host, stacked pass/fail/partial/blocked bar, status pill, duration, time, Demo badge.

**Run page:** header (ticket, "run 3 of 4", environment, account, started, duration, status, Claude cost, skill
versions), the friendly checklist read-only with evidence, links (open on board if present, open in Jira/Azure,
download spec files, full Playwright report), previous / next run of the ticket, **Compare with…**, **Report**
(§7).

**Compare:** default against the previous run of the same ticket. Items matched by normalised text; each tagged
**Fixed**, **Newly failing**, **Still failing**, **Unchanged**, **Added**, **Removed**. Summary line
("2 fixed · 1 newly failing · 7 unchanged") and flags when the environment or the spec hash differs.

**Ticket panel:** a "Runs (n)" list linking to each run page.

## 7. Reports screen

Route `#/reports`.

**Trends** (filters: date range, project, FE/BE): pass rate over time (day/week) with run counts; first-time pass rate
and average runs to green; flaky checks (same ticket, same environment and spec hash, result flipped pass↔fail),
with links to the runs; breakdown by project, FE/BE and issue type; time and Claude cost per ticket. Charts follow
the app's existing chart style (light/dark).

**Reports:**

1. **Run report:** summary, environment, account, every check with result, failure screenshots embedded, cost.
2. **Ticket report:** all runs of the ticket as a timeline to green, final checklist, the posted Jira comment, TestRail
   cases.
3. **Period summary:** tickets tested, runs, pass rate, bugs found by severity, most-failing areas, flaky checks, time
   and cost, each ticket with its final status.

Generated by `qa_app/workflow/reports.py` from history records into a self-contained HTML (images inlined). Saved
under `history/reports/<id>/` and listed on the Reports screen for re-download.

**Export:** HTML; PDF rendered from that HTML with Playwright's Chromium (`page.pdf`), no new dependency; CSV of runs
(index fields) and of check-level results.

**Send** (button + preview before sending; nothing is sent automatically):

- Slack / Teams: summary text (counts, failures, ticket keys) through the configured webhook;
- Jira: attach the PDF to the ticket (REST attachments with an API token; Atlassian MCP `uploadAttachmentToJiraIssue`
  with Atlassian sign-in). Azure Boards: attach via the work item attachments API.

Not included: scheduled reports.

## 8. API

- `GET /api/history?…filters` → summaries + strip totals
- `GET /api/history/{run_id}` → record; `GET /api/history/{run_id}/compare/{other}` → diff
- `GET /history-files/{run_id}/{path}` → evidence and HTML report (path-checked under the run folder)
- `POST /api/history/{run_id}/trace` → open Trace Viewer
- `GET /api/reports/trends?…` → trend series
- `POST /api/reports` {kind: run|ticket|period, ref, range} → report id; `GET /api/reports` list;
  `GET /api/reports/{id}.{html|pdf|csv}`
- `POST /api/reports/{id}/send` {to: slack|teams|jira} → result (requires the preview step in the UI)
- Live: existing `/api/events` stream gains `run` events {run_id, key, running_item, item result}.

## 9. Errors and edge cases

- Node / Playwright missing → run recorded as `error` with the message; ticket shows it as today.
- Playwright crashes mid-run → items not reported stay `nt`; run `error` with the tail of stderr.
- App restarts mid-run → on resume, an unfinished run folder is closed as `stopped`.
- Evidence file missing (pruned or deleted) → shown as "evidence removed", never a broken image.
- Report send fails → error shown on the preview; nothing retried silently.
- Paths served from history are resolved and must stay inside the run folder.

## 10. Testing

- `RunStore`: start/finish/fail, index rebuild, numbering, prune keeps last N, compare tags, status rule.
- Engine: a demo run and a faked live run (fake `npx` writing events.jsonl / results.json) produce records, update
  `running_item` and items as events arrive, post progress lines, and record `error` when the runner is missing.
- Reporter mapping: index and title fallback.
- Reports: HTML for each kind built from fixture runs; CSV columns; send builds the right payloads (HTTP faked).
- Trends: pass rate, first-time pass, flaky detection on fixtures.
- UI checked in a browser (light and dark): ticket live checklist, History list / run page / compare, Reports.

## 11. Build order

1. RunStore + engine recording (demo and live) + generated config and reporter + evidence.
2. Live feed and friendly checklist in the ticket.
3. History screen (list, run page, compare); remove Run screen and crawler.
4. Reports: trends, three report kinds, export, send.

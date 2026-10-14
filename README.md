# QA Engineer App

A Python + Playwright app that tests websites for you, and takes Jira tickets through a gated QA
workflow. Give it a URL and it crawls the site, runs the checks you pick, and produces an HTML report
plus JUnit XML. It can push results to Jira, Slack, Teams, TestRail, Xray, Zephyr Scale and AWS S3, and
the same engine runs headless in CI.

`run_app.bat` on Windows, `run_app.command` on macOS (or `python -m qa_app`) opens the app in your browser at http://127.0.0.1:8765:

| Screen | What it does |
|---|---|
| **Board** ⌘1 | Tickets from a Jira column (OPTR · Testing) in five lanes with four review gates: checklist → spec → run → Jira comment and move → TestRail cases. Each card shows its type (FE, BE or FE+BE) and the board filters by type |
| **Run** ⌘2 | The website checks below, with live findings, visual diffs (baseline / current / diff) and a log. Any finding can become a Jira issue |
| **History** ⌘3 | Issues per run per site, past runs, open report or folder, publish to integrations |
| **Integrations** ⌘4 | Every service, plus the Testing board and Claude settings. Test connection, then Save |

The original PySide window is still there: `run_classic.bat` / `run_classic.command` or `python -m qa_app --classic`.

## Checks

| Check | What it does |
|---|---|
| **Functional** | Crawls same-site pages (up to *Max pages*), flags HTTP errors, page load failures, uncaught JS exceptions, console errors, failed resource requests, broken internal/external links |
| **Visual regression** | Full-page screenshots per viewport (desktop / tablet / mobile), pixel diff against stored baselines, highlighted diff images |
| **Accessibility** | axe-core WCAG 2.1 A/AA + best-practice rules on every page |
| **SEO** | Title, meta description, h1, lang, viewport, canonical, noindex, missing alt text |
| **Performance** | Navigation timing and page weight on every page, plus Google Lighthouse (performance, a11y, best practices, SEO, LCP, CLS) on the first 3 pages. Lighthouse needs Node.js |

Severity: **critical** / **major** fail the run; **minor** / **info** are reported only.

## Setup (Windows)

```bat
setup.bat        :: one-time: venv + packages + Chromium
run_app.bat      :: start the app in your browser
run_classic.bat  :: the original desktop window
run_tests.bat    :: workflow tests (pytest)
```

Or manually: `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`,
`.venv\Scripts\python -m playwright install chromium`, `.venv\Scripts\python -m qa_app`.

**Already set up?** Run `setup.bat` once more (or `.venv\Scripts\pip install -r requirements.txt`) to add the
new packages: FastAPI, uvicorn and Jinja2.

## Setup (macOS)

Needs Python 3.10 or newer (`brew install python@3.12`, or the installer from python.org). Node.js is optional,
for Lighthouse and ticket specs (`brew install node`).

```bash
./setup.command        # one-time: venv + packages + Chromium
./run_app.command      # start the app in your browser (close the Terminal window to stop)
./run_classic.command  # the original desktop window
./run_tests.command    # workflow tests (pytest)
```

You can also double-click them in Finder. If macOS says it can't verify the file, right-click it, choose **Open**,
then **Open** again (only needed the first time). If a script won't start, run `chmod +x *.command` in the folder.

Or manually: `python3 -m venv .venv`, `.venv/bin/pip install -r requirements.txt`,
`.venv/bin/python -m playwright install chromium`, `.venv/bin/python -m qa_app`.

## Testing board (ticket workflow)

Each ticket in the Jira column goes through five lanes. Nothing reaches Jira or TestRail until you approve it in the ticket drawer.

| Gate | You review | Then the app |
|---|---|---|
| 1 Checklist | Scenarios and QA checklist, every item NOT TESTED | builds `<KEY>.spec.ts` (+ `.serial.spec.ts`) and runs it |
| 2 Results | Real results, bug notes, cleanup (each setting reverted and re-read), test data left behind | drafts the Jira comment |
| 3a Comment | The exact comment text (editable) | posts it, then lists the transitions Jira returns |
| 3b Move | The target state | moves the ticket, drafts TestRail cases (read-only lookup) |
| 4 Draft | Cases from PASS items only, duplicates removed | pushes only when you press **Push**, then verifies with `get_cases` |

The server enforces these rules, not just the UI:
- Each approval carries the state you saw, so it can't carry over to the next gate. Auto mode never skips a gate.
- Posting the comment does not move the ticket; the move is its own approval.
- Checklist results change only through a run.
- Jira transitions must match by exact name; a near miss returns the available list.
- A push never re-adds a case that already exists, so a retry after a partial failure only adds what is missing.
- An unmerged ticket without a PR or preview link stops at **Needs environment** instead of falling back to the shared environment.

**Ticket type.** Every ticket is **FE**, **BE** or **FE+BE**, taken from its Jira *Components* field. A ticket with
both a frontend and a backend component is FE+BE. Which component names count as which is set on the
**Testing board** card (*FE components*, *BE components*; defaults `Frontend, FE, Front-end, UI` and
`Backend, BE, Back-end, Core, API`, matched ignoring case). A ticket with none of them shows **No type**, so a
missing component is visible instead of guessed. The board's type filter (All · FE · BE · FE+BE) is remembered.
A frontend preview link is used as the test environment only for FE and FE+BE tickets.

**Demo data** is on by default: the board shows sample OPTR tickets and simulates Jira and TestRail, so you can try it
safely. To use your real column, set up **Jira** (and **TestRail**) on the Integrations screen, then untick
*Demo data* on the **Testing board** card. Live mode also needs:
- **Claude** turned on with an API key, so it writes the scenarios, checklist and spec. Without it the spec is a template with `test.fixme` stubs.
- A **Playwright workspace folder** (your Playwright repo). Ticket files go to `tests/tickets/<KEY>/` there and run with `npx playwright test --reporter=json`.
  Each checklist item is one test titled `[n] …`. A test can report PARTIAL or BLOCKED with
  `test.info().annotations.push({ type: 'qa-result', description: 'blocked: reason' })`.
- **SSO**: when no session is saved, gate 2 opens a browser on the environment. Sign in, press *I've signed in*, and the session is reused.

Board data lives in `%USERPROFILE%\.qa_app\workflow\` (`~/.qa_app/workflow/` on macOS). Demo and live tickets are kept apart, and demo files never go into your workspace.

## Desktop window (classic)

- **Run**: enter a URL, pick checks and viewports, then Run. Findings stream in live. Click one to see details and the screenshot or visual diff.
- **History**: every past run. Open its report or folder, or publish it to integrations after the fact.
- **Integrations**: configure each service, click *Test connection*, then Save.

Data lives in `%USERPROFILE%\.qa_app\` (`~/.qa_app/` on macOS: `runs/`, `baselines/`, `settings.json`), shared by the web UI, the classic window and the CLI.
To accept intended UI changes, tick *Accept current screenshots as new baselines* and run again.

## Integrations

| Service | What happens | Needs |
|---|---|---|
| Jira Cloud | One bug per finding at or above *min severity*, deduplicated across runs (a hidden label tracks it), screenshot attached | base URL, email, [API token](https://id.atlassian.com/manage-profile/security/api-tokens), project key |
| Slack | Run summary + top issues + report button | Incoming webhook URL |
| Teams | Same, as an Adaptive Card | Workflows / incoming webhook URL |
| TestRail | Auto-creates a test case per (check, page), creates a run, posts pass/fail with linked Jira defects | URL, user, API key, project id (suite id for multi-suite projects) |
| Xray Cloud | Imports JUnit as a Test Execution | client id/secret, project key |
| Zephyr Scale | Imports JUnit as a test cycle, auto-creating test cases | API token, project key |
| AWS S3 | Uploads the whole run folder. The report link (presigned for 7 days, or via `public_base_url`) is shared in Slack/Teams/Jira | Standard AWS credentials (profile, SSO, env, role) |

Any setting can be overridden with an env var: `QA_APP_<SECTION>_<KEY>`, e.g. `QA_APP_JIRA_API_TOKEN`.
Use env vars for secrets in CI.

## CLI / CI

```bash
python -m qa_app.cli https://example.com --checks all --max-pages 25 --publish --out qa-results
```

Options: `--checks functional,visual,accessibility,seo,performance|all`, `--viewports desktop,tablet,mobile`,
`--fail-on critical|major|minor|never` (exit code 1 when matched), `--publish [jira,slack,…]`,
`--update-baselines`, `--no-lighthouse`, `--headed`.

Ready-made pipelines in [`ci/`](ci/): GitHub Actions, GitLab CI, Bitbucket Pipelines. All three publish
JUnit to the platform's test view and keep the HTML report as an artifact. On GitHub a summary table is
also written to the job page.

## Project layout

```
qa_app/
  __main__.py        entry point: web UI (default) or --classic
  cli.py             headless entry point for CI
  runner.py          crawl + orchestrate checks
  checks/            functional, visual, accessibility, seo, lighthouse
  integrations/      jira, slack, teams, testrail, xray, zephyr, aws_s3
  report.py          HTML (templates/report.html.j2) + JUnit output
  web/               FastAPI server, Run bridge to runner.py, static front end
  workflow/          Testing board: ticket models, gated engine, checklist/spec/comment logic, demo data
  ui/                PySide6 window and background workers (classic)
tests/               pytest suite for the workflow rules and the report
ci/                  pipeline templates
```

# YourQA

A Python + Playwright app that takes Jira or Azure Boards tickets through a gated QA workflow with Claude:
it reads the ticket, writes the checklist and the Playwright spec, runs it, posts the Jira comment and drafts
TestRail cases, stopping at four review gates for you. Every run is kept in History with its evidence, and
Reports turns them into trends and shareable reports. The site crawler (HTML report + JUnit XML) still runs
headless in CI and in the classic window.

`run_app.bat` on Windows, `run_app.command` on macOS (or `python -m qa_app`) opens the app in your browser at http://127.0.0.1:8765:

| Screen | What it does |
|---|---|
| **Board** ⌘1 | Tickets from a Jira column (OPTR · Testing) in five lanes with four review gates: checklist → spec → run → Jira comment and move → TestRail cases. Each card shows its type (FE, BE or FE+BE) and the board filters by type |
| **History** ⌘2 | Every ticket test run: filters, each run's checks with screenshots / video / trace and the Playwright report, and comparison between two runs of a ticket |
| **Reports** ⌘3 | Trends (pass rate, first-time pass, runs to green, flaky checks, breakdowns) and run / ticket / period reports as HTML, PDF or CSV, sent to Slack, Teams, Jira or Azure Boards |
| **Integrations** ⌘4 | Every service, plus the Testing board and Claude settings. Test connection, then Save |
| **Skills** ⌘5 | How Claude does each board step: a general skill per step, refined per Jira project |

The original PySide window is still there: `run_classic.bat` / `run_classic.command` or `python -m qa_app --classic`.

## Checks (site crawler: CLI, CI and the classic window)

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

## Sign-in and first-run setup

When YourQA opens, you **sign in with Google** (any Google account; it tells YourQA who is testing, and your tickets
and keys stay on your computer). On first use a **setup** follows, one page per connection: Claude, where your tickets
are (Jira or Azure Boards), test cases (TestRail, Zephyr Scale or Xray), code and other tools (GitHub, MCP servers),
your test automation, and run summaries (Slack or Teams). Each page can be skipped, or set up right there with the
same forms as the Integrations screen. The last page lists what's connected and **Start studying** runs onboarding's
study, then opens the board. **Finish later** leaves setup; *Go through setup again* on the Onboarding screen reopens it.
Sign out from the bottom of the sidebar.

Google sign-in uses YourQA's own Google OAuth client, shipped with the app: in Google Cloud create an OAuth client of
type **Desktop app**, download its JSON and save it as `qa_app/google_client.json` (it's not in git), or set
`QA_APP_GOOGLE_CLIENT_ID` and `QA_APP_GOOGLE_CLIENT_SECRET`. Without a client the sign-in screen offers *Continue
without signing in*. `QA_APP_AUTH=off` turns sign-in off (CI).

## Onboarding

On the Onboarding screen (also reached from setup's last page), connect the tools your team uses (Jira or Azure Boards,
TestRail, Confluence through your Jira connection, and your automation as a folder or a repo link), choose the
projects, and press **Study**. YourQA reads a recent sample of each (about 200 tickets per project, 150 test cases,
30 docs pages and your automation repo; read-only) and Claude works out how your team does things. It then sets
YourQA up to match, straight away:

- skills for each project: how your tickets are written, how your QA comments, test cases and tests look;
- board settings: the QA column, which components mean frontend or backend, how test environment links look, and
  where tickets move after QA;
- a framework profile of your automation (language, runner, layout, page objects, helpers, run command);
- a company knowledge base (product areas, glossary, roles, environments) that Claude gets in every step.

While it studies, a **percentage bar** shows how far it is (it counts each project and each step Claude takes) with an
estimate of the time left; the sidebar shows the percentage too.

**What changed** lists every change with what it was based on. Changes apply straight away; mark each one **Keep** or
**Undo** (or **Keep all**). Undo leaves a change alone if you edited it yourself afterwards. When everything is decided,
**Finish onboarding**: what you kept is merged into the **general skills**, so it applies to every project. Claude
writes one clean section per step (*Your team's way*, at the end of the general skill) from what was learnt and the
knowledge base; onboarding's project versions are folded in and removed, except ones you edited yourself. The changes
become final and the Onboarding screen is put away.

**Onboarding is finished** then shows a summary: *What YourQA read* (each source and how much of it), *What it found*
(the evidence behind the changes, by area), *How your skills changed* (each step's added section, to read in full), and
*What else was set up* (board settings, move rules, knowledge base, framework profile). Each skill update is already in
use: **Accept** it, or **Revert** it to put the general skill and onboarding's project versions back exactly as they
were (a skill you edited after finishing is left alone). To study again later,
use the link on the Integrations screen.

**Tests in your style.** After onboarding has studied your automation repo, *Create tests* writes each ticket's
Playwright spec the way your team writes tests: Claude sees up to two of your own spec files and the signatures of your
page objects and helpers, and copies the patterns (naming, structure, tags, locators, test data). The spec stays in
YourQA's workspace and never imports your code. If your automation uses another framework (Cypress, pytest, Selenium),
YourQA still writes Playwright and says so once in the ticket's updates.

**Tests kept on a branch.** When a ticket is done, its folder (`tests/tickets/<KEY>/`) is committed to the local
branch `yourqa/<KEY>` in the workspace, for example *QA OPTR-48498: Device list filter (5 passed, 0 failed)*. Your
checked-out branch and files aren't touched, and nothing is pushed: push and open a PR yourself when you want. YourQA's
default workspace becomes a git repository on first use; a folder you chose that isn't one is left alone.

## Testing board (ticket workflow)

Each ticket in the Jira column goes through five lanes. Nothing reaches Jira or TestRail until you approve it in the ticket drawer.

| Gate | You review | Then the app |
|---|---|---|
| 1 Checklist | What was read from the ticket, then scenarios and QA checklist, every item NOT TESTED | builds `<KEY>.spec.ts` (+ `.serial.spec.ts`) and runs it |
| 2 Results | Real results, bug notes, cleanup (each setting reverted and re-read), test data left behind | drafts the Jira comment |
| 3a Comment | The exact comment text (editable) | posts it, then lists the transitions Jira returns |
| 3b Move | The target state | moves the ticket, drafts TestRail cases (read-only lookup) |
| 4 Draft | Cases from PASS items only, duplicates removed | pushes only when you press **Push**, then verifies with `get_cases` |

The server enforces these rules, not just the UI:
- Each approval carries the state you saw, so it can't carry over to the next gate. The board runs in gated mode: it never skips a gate.
- Posting the comment does not move the ticket; the move is its own approval.
- Checklist results change only through a run.
- Jira transitions must match by exact name; a near miss returns the available list.
- A push never re-adds a case that already exists, so a retry after a partial failure only adds what is missing.
- If the ticket has several links that could be the test environment (or only an unclear one), it stops at **Needs environment**, lists every link with the best one suggested and pre-filled, and you confirm it, pick another or type the address.

**What step 1 reads.** Everything on the ticket itself: summary, description, acceptance criteria, issue type,
status, priority, labels, components, fix and affects versions, sprint, story points, reporter and assignee, dates,
every other custom field by name, parent, subtasks and linked tickets (key, title, status), attachment names, web
links, and every comment with its author and date. It all goes into `<KEY>-context.md` and to Claude for the
checklist (oldest comments are trimmed first if a ticket is very long). The ticket drawer shows a summary.
Linked tickets and attachments are listed, not opened.

**Skills.** Each board column has a skill: Markdown instructions Claude gets every time it does that step
(Gather requirements, Create tests, Run tests, Jira comment, TestRail cases). The app ships a general skill for
each (`qa_app/skills/*.md`). On the **Skills** screen (⌘5, or the skill icon on a board lane) you can:
- edit the general skill for everyone (saved in `~/.qa_app/skills/general/`, *Reset to default* any time);
- add a version for a Jira project that **adds to** the general skill (default) or **replaces** it
  (`~/.qa_app/skills/projects/<KEY>/`), e.g. "our API is GraphQL", "always test the mobile viewport".
The ticket's Jira project decides which version is used, and the drawer shows which one Claude followed. Output
formats stay in the code, so editing a skill changes how Claude works, not what the app can read back.

The built-in general skills are product-neutral versions of the team's skills (gather-context, define-scenarios,
test-ticket, test-specs, unslop). The original EVA Suite Admin texts ship word for word as a built-in **OPTR**
project version that adds to them; saving your own OPTR version overrides it, and removing yours brings the built-in
one back. Skills can be up to 60,000 characters.

**Connected apps.** Before Claude gathers requirements, YourQA reads (read-only) what the connected apps know about
the ticket: GitHub PRs linked on it or mentioning its key (description, commits, changed files, diffs, review
comments; add a fine-grained read-only token on the GitHub card), Confluence pages linked on it or matching its key
or title (through your Jira connection), and matching TestRail cases. Each lookup is a line in the ticket feed, the
results are saved in `<KEY>-context.md` under "From connected apps", and later steps reuse them (Create tests gets
the PR diffs, the Run tests review gets the changed files). Long parts are trimmed, a failing app never stops the
step, and apps that aren't connected are named so Claude says what it couldn't check. Claude itself still has no
tools inside a step.

**Claude fetches what YourQA can't read.** When a lookup leaves a gap (a linked PR YourQA couldn't read, a file GitHub
left out of a diff, a Confluence page or design link it can't open, or no GitHub connection to search PRs by key), and
when Claude says during a step that it needs something, YourQA asks Claude Code to fetch it, read-only, then redoes the
step once with the findings. Claude may use read-style `gh` and `git` commands, the read tools of the MCP servers in your
Claude Code setup, web pages on the ticket's own domains, and read your Playwright workspace; Claude Code itself refuses
everything else. Each action shows live in the ticket's terminal. Claude Code mode only; switch it off on the Claude card
("Let Claude fetch missing data"). How it all fits together: `docs/ARCHITECTURE.md`.
With a Claude API key every step uses Claude and its skill: checklist, spec, bug notes and severity after a run,
the Jira comment, and the TestRail cases. Without a key, steps 3–5 fall back to the built-in templates.

**Integrations page.** Grouped by purpose (project management, AI, test case management, communication, board
settings). Connected services are one-line rows with a green check; click one to change it. Services you haven't set
up are listed once under *Add a service* at the bottom. When **Test connection** succeeds for a service that
is off, YourQA switches it on and saves it. Each has its own icon; to
show an official logo instead, put it in `qa_app/web/static/logos/<key>.svg` (see the README there).

**MCP servers.** Connect any remote MCP server (GitLab, Notion, Linear, Sentry, your own…) from *Add a service* →
*MCP server*: give it a name and its address, then sign in in the browser, paste a token, or choose none. YourQA lists
the server's tools in two groups. **Read tools** are on by default: YourQA runs them when a step asks for data
(gathering context, writing tests, reviewing results), Claude's fetching can use them, and onboarding can study the
server. **Write tools** are off; if you switch one on, Claude can only *propose* it in the ticket chat, showing the
exact call, and it runs only when you click **Run** (each one is logged in `<KEY>-mcp-writes.json`). Nothing is used
until you confirm the lists with **Save**. Only remote servers are supported; YourQA never starts programs on your
computer.

**Board sync and filters.** The board pulls its column automatically every 5 minutes while a real board is connected
(change or turn it off on Integrations → Testing board; a failed sync shows next to the sync button and waits a full
interval before retrying). **Filter** opens views by what a ticket needs (waiting on me, at a review gate, needs
attention, blocked, failing checks, Claude working) plus FE / BE, issue type and priority; active filters show as
removable pills.

**Where tickets come from: Jira or Azure Boards.** One card each; whichever column you pick last feeds the Testing board.

- *Jira*: paste the board link once, then choose how to sign in: **Atlassian sign-in** (no token to copy) or
  **email + API token** (when a site admin blocks the sign-in). Both read the same board and columns. The same
  connection files bugs from site checks: turn on "File bugs automatically after each site check" and pick the issue
  type and which findings.
- *Azure Boards*: paste the board link (`https://dev.azure.com/ORG/PROJECT/_boards/board/t/TEAM/Stories`) and a personal
  access token with **Work Items: Read & write**. Tags work like Jira labels and the area path like a component (FE / BE
  type); moving a ticket moves its card to another board column.

**Two ways to connect Claude** (Integrations › Claude › *Connection*):
- **API key**: an Anthropic API key from platform.claude.com, billed per use. Works for a team and in the background.
- **Claude Code on this computer**: for your own use, each step runs the `claude` command you're signed into with your
  Claude plan (`claude -p` with its tools and MCP servers off, so it only writes the answer, and API-key variables
  removed so it uses your plan login). Install Claude Code, run `claude` once to sign in, then *Test connection*.
  Costs then show as "≈ $x · your plan": what the same tokens would cost at API prices, not money spent.

**Claude cost per ticket.** Every Claude call records the exact tokens from the API reply (input, output, cache
writes and reads) on the ticket it was for, priced from Anthropic's list prices (`qa_app/workflow/costs.py`, e.g.
Sonnet 5.5 $2 / $10 per million input / output tokens). Cards show the ticket's cost, the drawer breaks it down by
step, and the board header shows the total. Redos add to it. A model without a known price is counted in tokens
and shown as unpriced, never guessed.

**Chat with Claude on a ticket.** In the ticket panel, switch to **Chat with Claude** to ask why it stopped, what to
test, or to change something. Claude sees the ticket, the environment and every link found, the checklist and results,
and the draft comment. It can suggest actions as buttons: redo step 1, test on another environment, retry, run the
tests again (Gate 2), replace the checklist (Gate 1), rewrite the Jira comment or pick the target status (Gate 3).
Nothing runs until you click, each suggestion is checked against where the ticket is at that moment, and Claude can
never approve a gate or post to Jira. Chat calls count in the ticket's Claude cost.

**Live ticket view.** While a ticket moves, the chat pane posts short updates (what was read, where it tests, each
check as it runs, gates reached), folded per step, plus a summary from Claude after step 1 and after each run. The
QA checklist shows counts, progress and one row per check with clear pass / fail / partial / blocked icons; the
running check spins live, and a failed check opens to its note, error, screenshot, video and trace, with **Ask Claude
about this**.

**Learning where tickets move.** After you move a ticket, Claude asks in the ticket chat whether to update the
**Jira comment & move** skill so it picks that state itself next time (for every board). Runs are grouped as all
passed, any failed, or blocked / partial; each has one rule, saved as a plain line under "Moving the ticket" in the
skill (editable on the Skills screen). Next time the comment is posted, that state is pre-selected and marked
"picked by the skill"; in Gated mode you still approve the move, and choosing another state asks again. A state Jira
doesn't offer for the ticket is never pre-selected.

**Skipping a step.** Every lane has **Skip this step** (click twice to confirm), also while it's working or after it
failed. The ticket moves on to the next lane; skipping never posts a comment, moves the ticket or pushes cases.
Skipping tests leaves checks not tested (the comment says so); skipping TestRail finishes the ticket. Skips show in
the feed and in History.

**TestRail cases.** In the last lane the drawer shows each drafted case in full: title, numbered steps and expected
result (click a case to open or close it), with the target section and how many duplicates were left out. The QA
checklist folds into one line there. `<KEY>-testrail-cases.md` has the same content. Nothing is pushed until you
approve at Gate 4.

**Terminal.** While a ticket runs, the drawer shows a **Terminal · Playwright** panel with every line Playwright
prints, live (saved as `terminal.log` in the run folder). The first run installs Playwright and Chromium in the test
workspace by itself, with the install output shown, and nothing ever waits for keyboard input. Claude turns key lines
into plain updates in the feed ("Playwright started: 6 tests"). When the run prints nothing for 45 seconds, Claude
says what it last printed, what that likely means (npm prompt, missing browser, site unreachable, sign-in page, slow
check) and how to unblock it. **Stop** ends the run; **Retry this step** starts it again.

**History.** Every run of a ticket's spec is recorded (`<app folder>/workflow/history/live/`, demo runs apart) with
its results, the spec that ran, and evidence: each run gets its own Playwright settings (the ticket's environment as
base URL, the saved SSO session, screenshots on failure or every check, video and trace for failures, JSON and HTML
reports). Evidence is kept for the last 5 runs of each ticket by default (Testing board settings); results are kept
forever. Open a run to see each check, the Playwright report and the spec files; **Compare with…** tags every check
fixed, newly failing, still failing, unchanged, added or removed.

**Reports.** Trends for a period, plus three reports built from History: a run report, a ticket report (every run to
green, the final checklist, the Jira comment, the move and TestRail cases) and a period summary (tickets, pass rate,
bugs by severity, failing areas, flaky checks, time and cost). Download as HTML, PDF (rendered with Playwright's
Chromium) or CSV. **Send** shows a preview first: Slack / Teams get a summary; Jira gets the PDF attached when
connected with an API token, or the summary as a comment with Atlassian sign-in (attaching files there would need the
app to run a shell command from the server); Azure Boards gets the PDF attached.

**Where to test.** Step 1 looks for the test environment in what the ticket says: the Environment field, custom
fields (e.g. "Preview URL"), web links, every comment (newest first) and the description. Each link is scored by
where it is, the words around it ("deployed to", "preview", "staging", "test on"…), and its address (preview / staging
/ qa / pr-123 style hosts, hosting platforms such as vercel.app, netlify.app, pages.dev). Code, design and docs links
and the Jira site are listed apart as *Other links*; production-looking links are never picked on their own. A link is used only when it
is clearly the environment and is the only such link; otherwise the drawer lists every link (best one marked *Suggested* and
pre-filled; tool, docs and file links under *Other links*) with a **Use** button each, or you type one. Addresses
typed without https:// count too. Once set, **Change** next to the environment lets you test on another link or address
(step 1 runs again for it).
For BE tickets an API link is preferred. On the **Testing board** card you can add *Environment hints* (your own
preview domains or words) and a *Default environment* that is used only for merged / done tickets.

**Redo step 1.** If the ticket changed in Jira (new comment, new link, edited description), press **Redo step 1** in
the drawer. It reads the ticket again and rebuilds the environment, scenarios and checklist. It works at the
checklist review, at Needs environment, after an error, and at the results review (that discards the run, so it
asks for a second click). An environment you picked yourself is kept. Once the Jira comment is posted, it's locked.

**Ticket type.** Every ticket is **FE**, **BE** or **FE+BE**, taken from its Jira *Components* field. A ticket with
both a frontend and a backend component is FE+BE. Which component names count as which is set on the
**Testing board** card (*FE components*, *BE components*; defaults `Frontend, FE, Front-end, UI` and
`Backend, BE, Back-end, Core, API`, matched ignoring case). Labels count too (e.g. `FE+BE`). A ticket with none
of them shows no FE/BE badge; the type is never guessed. The board's type filter (All · FE · BE · FE+BE) is remembered.
A frontend preview link is used as the test environment only for FE and FE+BE tickets.

**Connecting Jira.** On the Integrations screen, paste the link of the board you test from (for example
`https://your-site.atlassian.net/jira/software/projects/KEY/boards/1`) and press **Sign in with Atlassian**.
You approve access on Atlassian's page and land back in the app, which then shows the site, your account,
the project, the board and its columns with ticket counts. Pick the column that holds tickets ready for QA and
press **Show … on the Testing board**. No API token is needed.

This goes through [Atlassian's MCP server](https://github.com/atlassian/atlassian-mcp-server) (`mcp.atlassian.com`)
with OAuth 2.1, so the app can do only what your own Jira account can do. The first time on a site, a site admin
approves the app once; organisation admins can also restrict which apps may connect. The sign-in is stored in
`~/.qa_app/atlassian-mcp.json` and refreshed automatically. If your organisation blocks it, the
**Jira · API token** card is the fallback. That card is also what creates bugs from site-check findings.

**Demo data** is on by default: the board shows sample OPTR tickets and simulates Jira and TestRail, so you can try it
safely. To use your real column, set up **Jira** (and **TestRail**) on the Integrations screen, then untick
*Demo data* on the **Testing board** card. Live mode also needs:
- **Claude** turned on with an API key, so it writes the scenarios, checklist and spec. Without it the spec is a template with `test.fixme` stubs.
- A **Playwright workspace folder** (your Playwright repo). Ticket files go to `tests/tickets/<KEY>/` there and run with the workspace's own Playwright (installed there automatically on the first run).
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

**TestRail:** paste any page link of your project (its overview, a suite, a case or a run). YourQA takes the project and suite from it, asking TestRail when the page doesn't name them, and fills the fields in when you test the connection.


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
                     mcp_client.py (remote MCP + OAuth 2.1), atlassian_mcp.py (Jira through Atlassian's MCP server)
  report.py          HTML (templates/report.html.j2) + JUnit output
  web/               FastAPI server, Jira / Azure connect (jira_connect.py, azure_connect.py), static front end
  workflow/          Testing board: ticket models, gated engine, checklist/spec/comment logic, demo data,
                     skills.py (general + per-project step skills), environments.py, ticket_context.py,
                     history.py (run records), playwright_run.py (per-run config + live reporter),
                     reports.py (trends, reports, export, send), chat.py (Claude on a ticket)
  skills/            the general skill for each board step (Markdown), passed to Claude in that step
  ui/                PySide6 window and background workers (classic)
tests/               pytest suite for the workflow rules and the report
ci/                  pipeline templates
```

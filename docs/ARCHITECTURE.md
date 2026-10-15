# YourQA architecture

How YourQA is put together and why. Keep this file current: every change that adds or changes a module, a data flow,
a connection, a file on disk, or a safety rule updates the matching section here in the same commit (see `CLAUDE.md`).

Last updated: 2026-10-15 (TestRail project from the pasted link; Claude fetches missing data; connected-app lookups).


## 1. What it is

YourQA takes Jira (or Azure Boards) tickets through a gated QA workflow with Claude doing the work and a QA engineer
approving each gate:

```
Gather requirements ─▶ Gate 1 ─▶ Create tests ─▶ Run tests ─▶ Gate 2 ─▶ Jira comment ─▶ Gate 3a ─▶ Move ─▶ Gate 3b ─▶ TestRail draft ─▶ Gate 4 ─▶ push
```

It is a local app: a FastAPI server (`qa_app/web/server.py`) and a single-page UI in plain JavaScript
(`qa_app/web/static/app.js`), started with `python -m qa_app`. All state lives under the app folder
(`~/.qa_app`, or `QA_APP_HOME`). An older website crawler (`runner.py`, `checks/`, `cli.py`) still exists for CLI and CI
use, outside the board.


## 2. Layers

| Layer | Modules | Responsibility |
|---|---|---|
| UI | `web/static/app.js`, `app.css`, `tokens.css` | Renders from one state object; `render()` builds HTML and morphs it into the page (only changed nodes are touched). Live updates arrive over SSE. |
| HTTP API | `web/server.py`, `jira_connect.py`, `azure_connect.py` | Routes for the board, tickets, chat, history, reports, integrations, skills; serves static files with no-cache and versioned assets. |
| Workflow engine | `workflow/engine.py` | The lanes and gates, background steps (`spawn`), stop/retry, chat, auto-sync, the live feed (`say`) and terminal (`term`). |
| Step work | `workflow/agent.py` | One function per step: plan the checklist, write the spec, review results, write the comment, draft cases. Builds the prompts. |
| Claude | `agent.ask_claude`, `workflow/claude_code.py` | API mode (HTTPS, API key) or Claude Code mode (`claude -p` on the user's plan). |
| Knowledge | `workflow/skills.py`, `qa_app/skills/` | The skill text each step sends to Claude. |
| Lookups | `workflow/sources.py`, `integrations/github.py`, `confluence.py`, `testrail.py` | Read-only data from connected apps, and the gaps Claude is asked to fetch. |
| Running | `workflow/playwright_run.py`, `terminal.py` | Runs Playwright, streams its output, explains stalls. |
| Records | `workflow/history.py`, `reports.py`, `store.py` | Ticket state, run history with evidence, reports. |
| Trackers | `integrations/atlassian_mcp.py`, `mcp_client.py`, `jira.py`, `azure_boards.py`, `workflow/clients.py` | Jira via Atlassian MCP (OAuth) or REST token; Azure Boards via PAT; demo stand-ins. |


## 3. The workflow engine

- A `Ticket` (`workflow/models.py`) has a `stage` (lane 0–4) and `sub` (`working`, `gate`, `blocked`, …). The engine's
  `act(key, action, stage, sub)` checks the ticket is where the caller thinks it is, then runs the gate action.
  Stale actions are refused.
- Work between gates runs as background tasks (`Workflow.spawn`); one per ticket. **Stop** cancels it (and kills the
  Playwright process); **Retry** starts the step again.
- **Skip** (`Workflow._skip`, action `skip`) moves on without the current lane, whether it is working, failed or at its
  gate. It cancels the lane's work and never performs the lane's write: lane 1 → lane 2 with the checklist so far
  (lane 2 reports "No checks" if it is empty); lane 2 → Jira comment drafted (unrun checks stay not tested; an active run
  is recorded as `skipped`); 3a → move offered, nothing posted; 3b → TestRail drafting, status unchanged; lane 5 → ticket
  finished, nothing pushed. Each skip is said in the feed and added to the run record (`after.skipped`).
- Two stores: demo tickets and live tickets never mix (`TicketStore`, JSON on disk).
- Every change is published on the event bus (`store.bus`) and streamed to the browser over `/api/events`:
  `ticket`, `term` (terminal lines), `toast`, `sync`, `removed`.
- `say(key, text, step)` adds a line to the ticket's feed (the chat pane); `term(key, kind, text)` adds a line to the
  ticket's terminal panel.
- Auto-sync pulls the board column every few minutes; Gated mode means every gate waits for a person.


## 4. Claude

Two modes, chosen on the Claude card:

- **API**: `ask_claude` posts to the Messages API with the user's key.
- **Claude Code**: `claude_code.ask` runs `claude -p` with the step's instructions as the system prompt. For a normal
  step Claude has **no tools**: `--tools ""`, `--strict-mcp-config`, `--disallowedTools mcp__*`, `--max-turns 1`, in an
  empty working folder, with API-key variables removed so it uses the user's plan.

Every step's system prompt is: the step's fixed instructions (output format, `[n]` test titles, cleanup file) +
`NO_TOOLS` (what Claude can and can't do in a step) + `ASK_FOR_MORE` (only when fetching is possible) + the skill.
Token usage of every call is recorded per ticket (`costs.py`).

### 4.1 Claude fetches missing data

When YourQA can't see or read something, it asks Claude to fetch it, read-only.

```
YourQA lookups (sources.lookup) ─▶ gaps() ─▶ Claude fetch (claude_code.fetch) ─▶ saved in <KEY>-sources.json ─▶ step prompt
                                                     ▲
step answer says "need": [...]  ──────────────────────┘ ─▶ step asked again once with the findings
```

- **When**: (1) gaps after YourQA's own lookups: a linked PR it couldn't read (GitHub not connected or failing), a
  file GitHub left out of a diff because it's too large, a linked Confluence page it couldn't read, links it can't
  read at all (designs, documents), and a PR search by ticket key when GitHub isn't connected; (2) when Claude, doing
  Gather requirements, Create tests or the results review, says it needs something (`"need": [...]` in JSON answers,
  `// YOURQA-NEED:` lines in a spec). The step is then asked again once with the findings.
- **How**: `claude_code.fetch` runs `claude -p --output-format stream-json --permission-mode dontAsk`. Safety is
  enforced by Claude Code, not by the prompt:
  - `dontAsk` refuses every call that isn't on the allowlist, without prompting.
  - `--tools Bash,Read,Grep,Glob,WebFetch`: no edit or write tools exist in the session.
  - Allowlist: read-style `gh` (`pr view/diff/list/checks`, `search prs/code`, `issue/repo/release view`) and `git`
    (`clone/fetch/log/show/diff/branch/rev-parse/ls-remote/grep`); the read tools of the MCP servers in the user's
    Claude Code setup (found with `claude mcp list`; tools named `get*`, `list*`, `search*`, `fetch*`, `read*`, `view*`,
    `query*`, `find*`, `describe*`, `lookup*`, `executeRead`); `WebFetch` only for the domains linked on the ticket;
    reading files in the Playwright workspace and the ticket folder (`--add-dir`).
  - Deny list on top: `Edit`, `Write`, `NotebookEdit`, `gh api`, `git push/commit/reset/checkout`, `rm`, `curl`, `wget`.
  - Working folder: `<app>/claude-code/fetch/<KEY>/` (scratch). At most 15 turns and 4 minutes per fetch.
- **Visibility**: each action Claude takes is streamed into the ticket's terminal panel (`▸ gh pr diff 512 …`), refused
  actions are shown as refused, and the feed says what was asked and what came back.
- **Where it's kept**: `Sources.fetched` in `<KEY>-sources.json`; shown to later steps as "Fetched by Claude".
- **Availability**: Claude Code mode only, and the Claude card's "Let Claude fetch missing data" switch (on by default).
  In API mode the gaps are still listed and the feed says why nothing was fetched.
- **Prompt injection**: fetched text is wrapped and labelled as information written by other people, never
  instructions; the fetch session itself can only read.


## 5. Connected-app lookups (read-only)

`sources.lookup` runs before Gather requirements (`Workflow._lookups`), off the event loop:

| Source | Connection | What it reads |
|---|---|---|
| GitHub | GitHub card: fine-grained read-only token, optional repos/orgs | PRs linked on the ticket, then PRs mentioning the key (up to 4): description, commits, changed files, diffs, review comments |
| Confluence | The Jira connection (MCP sign-in or REST token on the same site) | Pages linked on the ticket, then pages matching the key or title (up to 3) |
| TestRail | TestRail card: paste any page link of the project; the project (and suite) are taken from it (`testrail.resolve`) | Cases whose title matches the key or title (up to 40) |

- Results are trimmed (PR body 3k, per-file patch 0.8k for gathering / 2.5k for writing tests, diff total 12k / 30k,
  page 6k), wrapped in `<connected_apps>`, and saved as `<KEY>-sources.json`; `<KEY>-context.md` gets a "From
  connected apps" section.
- Later steps reuse the saved lookups: Create tests gets diffs, the results review gets changed files and commits.
- Each lookup posts a feed line; a failing app is reported and the step continues; unconnected apps are named so Claude
  says what it couldn't check.


## 6. Skills

- One skill per step (`gather`, `create-tests`, `run-tests`, `jira-comment`, `testrail`), Markdown, up to 60k chars.
- Layers, resolved by `skills.effective(step, project)`:
  1. **Built-in general** (`qa_app/skills/<step>.md`): product-neutral, based on the team's skills.
  2. **Your general** (`<app>/skills/general/<step>.md`): replaces the built-in one; Reset brings it back.
  3. **Project version**: yours (`<app>/skills/projects/<KEY>/<step>.md`) or built-in
     (`qa_app/skills/projects/<KEY>/<step>.md`; **OPTR** ships with the team's original EVA Suite Admin texts). Mode
     *add* appends to the general skill, *replace* replaces it. Yours overrides the built-in one.
- Learned move rules (`move_rules.py`): after a move, Claude offers to save the chosen state as a rule in the general
  Jira comment skill ("When any check fails: move to "To Do""); next time that state is pre-selected.


## 7. Running tests

- `playwright_run.run` writes a per-run `playwright.config.js` (CommonJS) and the `yourqa-reporter.js` reporter into
  the run folder, then runs the workspace's own Playwright binary with stdin closed.
- First run in a workspace: `prepare_workspace` creates `package.json`, runs `npm install` and
  `playwright install chromium`, with the output shown.
- The reporter writes `events.jsonl` (begin/end per check, keyed by the `[n]` title prefix); the engine tails it to
  update the checklist live.
- Every stdout/stderr line goes to the ticket's terminal; silence longer than 45s is reported with the last line and a
  likely cause (`terminal.stall_message`). Output is saved as `terminal.log`.
- Evidence: screenshots, video and trace on failure (or every check), JSON and HTML reports.


## 8. Data on disk

Under the app folder (`~/.qa_app`):

| Path | What |
|---|---|
| `settings.json` | All settings (Integrations screen); secrets included, local only |
| `atlassian-mcp.json` | Atlassian OAuth tokens and client registration |
| `workflow/tickets.json`, `tickets-demo.json` | Ticket state |
| `workflow/history/live/<run-id>/` | One run: `run.json`, config, reporter, `events.jsonl`, `results.json`, `terminal.log`, evidence, spec copy |
| `workflow/history/live/_reports/` | Saved reports (HTML, PDF) |
| `skills/general/`, `skills/projects/<KEY>/` | Your skill edits |
| `claude-code/` | Empty working folder for `claude -p`; `fetch/<KEY>/` scratch folders for fetching |
| `workspace/` (or the configured repo) | The Playwright workspace; ticket files in `tests/tickets/<KEY>/` |

Ticket folder `tests/tickets/<KEY>/`: `<KEY>-context.md`, `-scenarios.md`, `-qa-checklist.md`, `.spec.ts`,
`.serial.spec.ts`, `-report.md`, `-testrail-cases.md`, `-sources.json`, `-errors.json`, `-cleanup.jsonl`.


## 9. Safety rules

- Every external write (Jira comment, move, TestRail push, report send) happens only on the user's gate approval;
  approvals never carry over.
- Claude never approves gates; chat suggestions are buttons the user clicks, checked against the ticket's current state.
- Lookups and fetches are read-only (sections 4.1, 5). Fetched content is data, not instructions.
- A comment is checked against the ticket's latest comments before posting and after a lost reply, so it is never
  posted twice.
- YourQA never runs shell commands supplied by a remote server; sending a report to Jira over MCP posts a summary
  comment instead of uploading a file.
- Secrets are entered by the user on the Integrations screen and stay in the local settings file.

### Connection setup helpers

- Jira: paste a board link, sign in with Atlassian (MCP) or use an API token (`jira_connect.py`).
- Azure Boards: paste a board link plus a PAT (`azure_connect.py`).
- TestRail: paste any page of the project. `testrail.parse_link` reads the site and whatever the page names (project,
  suite, case, run); `testrail.resolve` fills the project and suite: typed values first, then the link, then TestRail
  (a suite, case or run's project, or the only project there is; with several it lists them). The connection test
  returns the filled-in fields so the card shows them; saving stores the clean site address and, when the link
  names only a suite, case or run, asks TestRail for its project. If the project is still missing when the board needs
  TestRail (`clients.RealTestRail`, case search), it is worked out the same way and saved to the settings.


## 10. Testing

`tests/` holds pytest suites per area (`test_workflow`, `test_sources`, `test_claude_code`, `test_skills`,
`test_playwright_run`, `test_history`, `test_reports`, `test_jira_mcp`, `test_trackers`, …). External services are
faked: a fake Atlassian MCP server, fake GitHub/Confluence/TestRail objects, and stand-in `claude`, `npm` and
`playwright` executables.


## 11. Decisions log

Newest first. Specs live in `docs/superpowers/specs/`.

- 2026-10-15: Every lane can be skipped (working, failed or at its gate); skipping never writes to Jira or TestRail and is recorded in History.
- 2026-10-15: Lane 5 shows the drafted TestRail cases in full (steps, expected) and folds the checklist away; `<KEY>-testrail-cases.md` includes steps and expected results.
- 2026-10-15: A TestRail project missing from the settings is worked out on first use (suite, link or only project) and saved.
- 2026-10-15: TestRail card takes the project (and suite) from a pasted page link; Project ID is no longer required.
- 2026-10-15: Claude fetches missing data with read-only tools enforced by Claude Code (`dontAsk` + allowlist), on gaps
  and when a step asks; streamed to the terminal.
- 2026-10-15: Connected-app lookups before gathering (GitHub card, Confluence via Jira, TestRail); YourQA fetches,
  Claude stays tool-less in steps. Spec: `2026-10-15-connected-apps-and-general-skills-design.md`.
- 2026-10-15: Built-in skills are product-neutral; the team's EVA texts ship as a built-in OPTR project version.
- 2026-10-15: Learned move rules in the Jira comment skill.
- 2026-10-15: Live terminal, stall explanations, Stop; Playwright installed into the workspace, never `npx` prompts.
- 2026-10-15: UI updates by morphing the DOM (no full re-render), fixing flicker and chat auto-scroll.
- 2026-10-15: History and Reports replace the old Run screen. Spec: `2026-10-15-history-reports-design.md`.

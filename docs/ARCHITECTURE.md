# YourQA architecture

How YourQA is put together and why. Keep this file current: every change that adds or changes a module, a data flow,
a connection, a file on disk, or a safety rule updates the matching section here in the same commit (see `CLAUDE.md`).

Last updated: 2026-10-26 (General and personal skill trees; onboarding builds the personal tree).


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
| UI | `web/static/app.js`, `app.css`, `tokens.css` | Renders from one state object; `render()` builds HTML and morphs it into the page (only changed nodes are touched). Live updates arrive over SSE. Screens show what needs a decision; secondary details (ticket fields, runs, files, cost) sit in folded sections (`foldSection`). No all-caps labels, middle-dot meta strings or monospace keys. Look: orange accent on cream (light) or warm charcoal (dark), layered gradient backgrounds with a faint grain (`--atmo`, `.qa::before`), translucent blurred surfaces; Instrument Sans for text, Bricolage Grotesque for headings, JetBrains Mono for code, loaded from Google Fonts with system fallbacks. |
| Sign-in | `auth.py` | Google sign-in (authorization code + PKCE, YourQA's own Desktop client), sessions in an HttpOnly cookie; the API refuses requests without one. |
| HTTP API | `web/server.py`, `jira_connect.py`, `azure_connect.py` | Routes for the board, tickets, chat, history, reports, integrations, skills; serves static files with no-cache and versioned assets. |
| Workflow engine | `workflow/engine.py` | The lanes and gates, background steps (`spawn`), stop/retry, chat, auto-sync, the live feed (`say`) and terminal (`term`). |
| Step work | `workflow/agent.py` | One function per step: plan the checklist, write the spec, review results, write the comment, draft cases. Builds the prompts. |
| Claude | `agent.ask_claude`, `workflow/claude_code.py` | API mode (HTTPS, API key) or Claude Code mode (`claude -p` on the user's plan). |
| Knowledge | `workflow/skills.py`, `qa_app/skills/general/` | The general (read-only) and personal (editable) skill trees, which one each project uses, and the text each step sends to Claude. |
| Lookups | `workflow/sources.py`, `integrations/github.py`, `confluence.py`, `testrail.py` | Read-only data from connected apps, and the gaps Claude is asked to fetch. |
| MCP servers | `integrations/mcp_servers.py`, `mcp_client.py` | Remote MCP servers added on the Integrations page: tool lists sorted into read and write, read calls for steps, fetching and onboarding, write calls only after the user clicks Run. |
| Running | `workflow/playwright_run.py`, `terminal.py` | Runs Playwright, streams its output, explains stalls. |
| Frameworks | `frameworks/__init__.py`, `base.py`, `playwright_ts.py`, `keep.py` | Picks the adapter for the company's framework (Playwright TS for now), gives Claude the company's style examples, keeps finished tickets' tests on a local branch. |
| Records | `workflow/history.py`, `reports.py`, `store.py` | Ticket state, run history with evidence, reports. |
| Onboarding | `onboarding/collect.py`, `analyze.py`, `apply.py`, `run.py` | Studies a company's tools; applies settings, a framework profile and a knowledge base, with Undo; builds the personal skills at Finish. |
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


## 5c. Sign-in and first-run setup

Spec: `docs/superpowers/specs/2026-10-16-sign-in-and-setup-design.md`.

- **Google sign-in** (`auth.py`): YourQA's own OAuth client (Desktop app type) from `qa_app/google_client.json` (not in
  git; the file Google Cloud downloads works) or `QA_APP_GOOGLE_CLIENT_ID`/`_SECRET`. `/api/auth/google/start` sends
  the browser to Google with PKCE and a one-time state; `/api/auth/google/callback` exchanges the code server to
  server, checks the ID token (audience, issuer, expiry, verified email), and sets the session cookie. Redirects use
  `http://127.0.0.1:<port>` so the cookie and the app share one host. Any Google account may sign in.
- **Sessions**: a random token in the `yourqa_session` cookie (HttpOnly, SameSite=Lax, 30 days); only its SHA-256 is
  stored, with the person, in `<app>/sessions.json` (owner-only). The `require_session` middleware answers 401 to any
  `/api/` request without one, except `/api/auth/*` and the Jira and MCP OAuth callbacks (protected by their own
  state); the app then shows the sign-in screen. Without a Google client, *Continue without signing in* makes a guest
  session; once a client exists guests must sign in. `QA_APP_AUTH=off` turns it all off.
- The signed-in person shows at the bottom of the sidebar (Sign out), and MCP writes they run record their email.
- **Setup** (`#/setup/<page>`, full screen): Claude, tickets (Jira or Azure Boards), test cases (TestRail, Zephyr
  Scale, Xray), code and tools (GitHub, MCP servers), test automation, run summaries (Slack, Teams), and a last page
  that lists what's connected and starts onboarding's study. Pages reuse the Integrations forms; a Jira or MCP browser
  sign-in started there returns to the same page. Shown after sign-in while `app.setup_done` is false; Finish later or
  finishing sets it.


## 5b. MCP servers (Integrations page)

Any remote MCP server (Streamable HTTP) can be added on the Integrations page. Spec:
`docs/superpowers/specs/2026-10-16-mcp-servers-design.md`.

- **Adding**: name, address (https, or http on localhost), and sign-in: in the browser (OAuth 2.1 with PKCE and
  dynamic registration, the flow Jira uses; callback `/api/mcp/oauth/callback`), a token the user pastes (sent as
  `Authorization: Bearer …` or a header they name), or none. YourQA never starts local servers or runs commands.
- **Tools**: `mcp_servers.classify` sorts each tool: the server's `readOnlyHint`/`destructiveHint` first, then a
  read-sounding name (get, list, search, read, find, query, fetch, …). Read tools start on, write tools off. Nothing
  runs until the user confirms the lists with Save (`confirmed`). Test connection lists the tools again; a dropped tool
  leaves the lists, a new one stays off.
- **Steps**: every step's instructions list the confirmed read tools in `<mcp_tools>` (both Claude modes). Claude asks
  with a `need` entry `mcp: <server> <tool> {json}`; `Workflow._fetch` runs it through `mcp_servers.call_read` (which
  refuses anything not confirmed as a read tool), up to 10 calls per request, each result trimmed to 20,000
  characters, shown in the terminal, saved in `Sources.fetched` and given back wrapped in `<mcp_results>` as data.
  Other requests still go to Claude's fetching.
- **Claude's fetching** (Claude Code mode): the confirmed servers go to `claude -p` in a temporary `--mcp-config`
  (owner-only, deleted after the run) with only `mcp__yq_<server>__<tool>` read tools allowed.
- **Onboarding**: a server with confirmed read tools can be ticked on the Connect step. Claude picks up to 10 read
  calls from the catalog (`analyze.plan_mcp`, unknown tools dropped), YourQA runs them, and the results feed the
  knowledge base (`collected/mcp.json`).
- **Write tools**: only ones the user switched on. Claude can only propose one in the ticket chat (`mcp_write`
  suggestion showing server, tool and exact arguments). It runs when the user clicks Run (`Workflow._run_mcp_write`,
  checked again first), is logged in `<KEY>-mcp-writes.json`, and Don't run marks it so it can't run later. Steps never
  call write tools.
- Servers set up in Claude Code are listed under the group for reference; Claude's fetching already uses their read
  tools.


## 5a. Onboarding

The first thing a company does: connect its tools; YourQA studies a recent sample of each and sets itself up their way.
Spec: `docs/superpowers/specs/2026-10-16-onboarding-design.md`; plan: `docs/superpowers/plans/2026-10-16-onboarding.md`.

```
collect (read-only, bounded) ─▶ analyze (Claude, tool-less, JSON per area) ─▶ apply each area as it finishes ─▶ summary + Undo
```

- **Collect** (`collect.py`): tracker `recent(project, 200)` on every client (Jira REST, Jira MCP, Azure Boards, demo) plus
  what the sample shows (statuses, components, labels, types, transitions); TestRail `sample()` (section tree, 150 most
  recently updated cases with steps); Confluence pages linked from the tickets, then the latest in chosen spaces (30,
  each 6k chars); the automation repo from a folder or a link (`git clone --depth 1` into `company/repos/`): tree,
  configs, CI, docs, then real specs, page objects and helpers (most recent, one per folder), capped at 120k chars.
  Heavy folders (`node_modules`, `.git`, venvs, build output) and secret files (`.env`, keys) are never read.
- **Analyze** (`analyze.py`): tickets in batches of 50 (observations) then one combine call → settings (board column,
  FE/BE components, environment hints), move rules, Gather requirements and Jira comment skill versions; TestRail →
  TestRail skill version and a section map; Confluence + tickets → knowledge base; repo → framework profile and a Create
  tests skill version. Each answer carries evidence. A failing area is reported; the others count.
- **Apply** (`apply.py`): skill lessons (`<PROJECT>/<step>`) are only recorded, for Finish; settings go to their
  sections (`workflow.*`, `testrail.section_map`); move rules go into the personal Jira comment skill (Undo removes a
  personal tree the move rule created, if nothing else changed in it); the knowledge base
  and profile become `company/knowledge.md` and `company/profile.json`. Each change records the value before it;
  **Undo** restores it only while it still holds onboarding's value (a later edit of yours is left alone); **Undo all**
  unwinds the run. Changes that replaced your own edit are marked.
- **Use**: `agent.company_context()` adds the knowledge base to every step's system prompt; `agent.framework_note()`
  adds the profile to the Create tests prompt; the TestRail draft uses the learned section map.
- **Runs** (`run.py`): one study at a time; progress on the bus (`type: onboarding`); Stop keeps the areas already
  applied; a run the app didn't finish is marked stopped on restart.
- **Progress**: one unit per project read (`collect_tracker(on_project=…)`) and per other source, then one per Claude
  call (`analyze.count_calls`; `analyze` calls `on_step` after each). The total starts as an estimate (about 5 units per
  project) and is recounted after collecting; the percentage only goes up and stays below 100 until the run ends. Events
  `{"event": "progress", "percent", "text"}`; `state()["progress"]` has the start time, so the screen shows an estimate
  of the time left. The sidebar shows the percentage, or how many changes are still undecided.
- **Keep or Undo**: changes still apply straight away; each is then kept (`apply.keep`, `keep_all`) or undone.
  `undecided()` counts the rest.
- **Finish onboarding** (`Onboarding.finish`, `/api/onboarding/finish`): only when every change is kept or undone.
  `skills.create_personal()` copies every general skill the personal tree doesn't have (an existing personal tree is
  kept and built on). For each step with kept lessons, the lessons (deduplicated across projects, labelled by project
  when they differ) go to `analyze.improve` with the current text of every skill in the step's branch (personal, else
  general), the knowledge base and, for Create tests, the profile. Claude returns the whole improved text of each skill
  the lessons bear on, with the conventions worked in place; the others stay copies. A failed call appends the lessons
  to the step's own skill under "Your team's way". The studied projects get `skills.choice = personal`. `finish.json`
  holds one entry per changed skill (`node`, `step`, names, `from` projects, `added` lines, `before`, `before_file`,
  `after`, `state`, `fallback`) and the projects switched. The run becomes `finished` (no more Undo), and
  `app.onboarding_done` hides the Onboarding screen from the sidebar. Integrations links back to it; starting a new
  study brings it back. The general tree is never written.
- **Finished summary**: `state()["last"]["finish"]` lists each changed skill without `before`/`after`.
  `accept_merge(node)` marks it; `revert_merge(node)` (`/api/onboarding/merge/{node}/accept|revert`) puts the personal
  skill back as it was before Finish (or the general text, when it had no personal file), only while it still holds
  what Finish wrote ("changed since" otherwise).
- **Screen**: Connect · Choose · Study · What changed, in one column; once finished, a short summary with Study again.

## 6. Skills

- A tree, `qa_app/skills/general/tree.json`: the five board steps (`gather`, `create-tests`, `run-tests`,
  `jira-comment`, `testrail`), each with child skills (gather → context, scenarios, checklist; create-tests →
  spec-conventions, page-objects, test-data, ui-timing; run-tests → triage, bug-notes; jira-comment → qa-summary,
  remarks, writing; testrail → case-writing, from-manual). One Markdown file per skill with front matter (`name`,
  `parent`), up to 60k chars. A step's text is its own skill followed by its children, joined by `---`.
- **General** (`qa_app/skills/general/`): ships with the app, product-neutral (written from the team's skills, no
  product names). Read-only: nothing in the app writes it.
- **Personal** (`<app>/skills/personal/<skill>.md`): the same shape, editable. Made by Finish onboarding, by Copy the
  general skills (`create_personal`), or by the first save or learned move rule. A skill file missing from it is the
  general one. `reset_personal(skill)` writes the general text back.
- **Choice per project** (`skills.choice` in settings: `{KEY: personal|general}`): personal is recommended and the
  default once the personal tree exists. `skills.effective(step, project)` returns the text and which tree it came
  from; `for_prompt` wraps it as `<skill step=… source=…>`; the ticket records the source per step.
- Routes: `GET /api/skills?project=` (both trees, `changed` per skill, the choice), `POST /api/skills/personal`,
  `PUT|DELETE /api/skills/personal/{skill}` (save, reset to general), `PUT /api/skills/choice/{project}`.
- Migration (`skills.migrate()`, at startup): edits in the old `skills/general/` and `skills/projects/<KEY>/` are
  appended to the matching personal skills (project ones under "For project KEY"), then the old folders move to
  `skills/_before-personal/`. The built-in OPTR project version is gone.
- Learned move rules (`move_rules.py`): after a move, Claude offers to save the chosen state as a rule in the personal
  Jira comment skill (making the personal tree if needed, and switching the project to personal); next time that
  state is pre-selected.

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

### 7a. Framework adapters

Spec: `docs/superpowers/specs/2026-10-16-framework-adapters-design.md`.

- `frameworks.pick(profile)` picks the adapter from `company/profile.json`. The first version has one,
  `PlaywrightTS`; when the profile names another framework it still uses Playwright and returns a note that the feed
  shows once per ticket (`Workflow._framework_note`).
- `Adapter.style_examples(company)` reads the latest onboarding study's `collected/repo.json`: up to 2 of the
  company's spec files (4,500 characters each) and the signatures (no bodies) of their page objects and helpers, 12,000
  characters in all. `agent.framework_note()` adds them to the Create tests prompt in `<company_style>`, labelled as
  data, with the rule that the spec never imports from the company's repo.
- `keep.commit_ticket(workspace, key, message, init)` runs when a ticket finishes (`Workflow._keep`, after the
  TestRail push or a skip): it commits `tests/tickets/<KEY>/` to `refs/heads/yourqa/<KEY>` with plumbing
  (`hash-object`, a temporary `GIT_INDEX_FILE`, `write-tree`, `commit-tree`, `update-ref`), so HEAD, the index and the
  working tree are untouched; an unchanged folder adds no commit. Only YourQA's default workspace is `git init`-ed; a
  chosen folder that isn't a repository is reported in the feed. Nothing is pushed.


## 8. Data on disk

Under the app folder (`~/.qa_app`):

| Path | What |
|---|---|
| `settings.json` | All settings (Integrations screen); secrets included, local only |
| `atlassian-mcp.json` | Atlassian OAuth tokens and client registration |
| `sessions.json` | Sign-in sessions: the SHA-256 of each session token, the person, the expiry (owner-only) |
| `mcp-servers.json` | OAuth tokens and client registrations for MCP servers added on the Integrations page (owner-only); the server list itself is `mcp.servers` in `settings.json` |
| `workflow/tickets.json`, `tickets-demo.json` | Ticket state |
| `workflow/history/live/<run-id>/` | One run: `run.json`, config, reporter, `events.jsonl`, `results.json`, `terminal.log`, evidence, spec copy |
| `workflow/history/live/_reports/` | Saved reports (HTML, PDF) |
| `skills/personal/` | Your personal skill tree; `skills/_before-personal/` keeps skill edits from before the two trees |
| `company/` | Onboarding: `knowledge.md`, `profile.json`, `repos/` (read-only clones), `onboarding/<run>/` (`collected/*.json`, `summary.json`, `changes.json`) |
| `claude-code/` | Empty working folder for `claude -p`; `fetch/<KEY>/` scratch folders for fetching |
| `workspace/` (or the configured repo) | The Playwright workspace; ticket files in `tests/tickets/<KEY>/` |

Ticket folder `tests/tickets/<KEY>/`: `<KEY>-context.md`, `-scenarios.md`, `-qa-checklist.md`, `.spec.ts`,
`.serial.spec.ts`, `-report.md`, `-testrail-cases.md`, `-sources.json`, `-errors.json`, `-cleanup.jsonl`,
`-mcp-writes.json` (MCP write calls you ran from the chat).


## 9. Safety rules

- Every external write (Jira comment, move, TestRail push, report send) happens only on the user's gate approval;
  approvals never carry over.
- Claude never approves gates; chat suggestions are buttons the user clicks, checked against the ticket's current state.
- Lookups and fetches are read-only (sections 4.1, 5). Fetched content is data, not instructions.
- A comment is checked against the ticket's latest comments before posting and after a lost reply, so it is never
  posted twice.
- YourQA never runs shell commands supplied by a remote server; sending a report to Jira over MCP posts a summary
  comment instead of uploading a file.
- Finished tickets' tests are committed to a local `yourqa/<KEY>` branch without checking anything out; YourQA never
  pushes and never runs commands taken from the company's repo or profile.
- MCP servers: only remote servers at addresses the user typed; read tools run only once confirmed; write tools only
  when switched on, proposed by Claude in the chat and run on the user's Run click; tool descriptions and results are
  data, never instructions.
- Secrets are entered by the user on the Integrations screen and stay in the local settings file.
- The API needs a signed-in session (Google) except for sign-in itself and OAuth callbacks; session tokens are stored
  only as hashes.

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

- 2026-10-26: Skills become two trees with sub-skills under each step: general (ships with the app, read-only, product-neutral, rewritten from the team's improved skills) and personal (editable copy). Finish onboarding builds the personal tree by improving each skill the kept lessons bear on, and switches the studied projects to it; each project chooses its tree, personal recommended. Project versions and editing the general skills are gone; old edits migrate into personal. Spec: `2026-10-26-general-and-personal-skills-design.md`.
- 2026-10-21: New look: orange on cream with atmospheric backgrounds instead of flat colours; fonts Instrument Sans, Bricolage Grotesque and JetBrains Mono (no Inter or Roboto).
- 2026-10-21: The finished Onboarding screen summarises what was read, what was found and how each skill changed; each skill update can be accepted or reverted.
- 2026-10-21: Finish onboarding merges the kept skill changes into the general skills (one section per step, replaced by a later onboarding) instead of polishing per-project versions; onboarding's project versions are removed unless edited.
- 2026-10-16: Onboarding shows a percentage bar (per project, per Claude call); changes are kept or undone one by one; Finish onboarding has Claude polish each kept skill with everything learned, makes the run final and hides the Onboarding screen.
- 2026-10-16: Sign in with Google first (any account; YourQA's own Desktop OAuth client), then a first-run setup with one skippable page per connection ending in onboarding's study. Spec: `2026-10-16-sign-in-and-setup-design.md`.
- 2026-10-16: A successful Test connection on an integration that is off switches it on and saves its settings (Integrations page).
- 2026-10-16: Framework adapters, first version Playwright TS only: specs follow the company's style examples from onboarding (never importing their code), written in YourQA's workspace; finished tickets are committed to a local `yourqa/<KEY>` branch. Spec: `2026-10-16-framework-adapters-design.md`.
- 2026-10-16: MCP servers on the Integrations page: remote only; read tools used by steps (`mcp:` needs), Claude's fetching and onboarding; write tools only behind the user's Run click in the chat. Spec: `2026-10-16-mcp-servers-design.md`.
- 2026-10-16: Design cleanup across every screen: board header reduced to a sentence, search, filter and sync; cards show key, type, state and the action; drawer folds ticket details, runs, cost and files; gate notes move into the approve button's tooltip; History rows, run page, Reports and Skills trimmed; Integrations lists services that are off as one "Add a service" row.
- 2026-10-16: Onboarding (collect → analyse → apply with Undo) as the first of three projects for selling to companies (then framework adapters, then continuous learning).
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

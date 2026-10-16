# Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A company connects its tools; YourQA studies a recent sample of each and applies tailored skills, settings, a framework profile and a knowledge base, with Undo per change.

**Architecture:** New package `qa_app/onboarding/`: `collect.py` (bounded read-only samples per source), `analyze.py` (tool-less Claude calls with JSON contracts, batched), `apply.py` (changes with before-values, undo), `run.py` (orchestrates a study run, emits progress on the event bus). Server routes and one clean UI screen on top. Company files live under `<app>/company/`.

**Tech Stack:** Python 3 (FastAPI, requests, pydantic), plain JS UI, pytest-style tests run with the repo's runner.

**Spec:** `docs/superpowers/specs/2026-10-16-onboarding-design.md`

## Global Constraints

- Read-only everywhere: collectors never write to Jira, Azure, TestRail, Confluence or the repo; repo links are cloned into `<app>/company/repos/<name>` (`git clone --depth 1`).
- Samples: tracker last 200 tickets per chosen project; TestRail 150 recent cases; Confluence up to 30 pages, each trimmed to 6,000 chars; repo selection capped at 120,000 chars total.
- Analysis calls are tool-less (`agent.ask_claude`), batches of 50 tickets, then one combine call per area.
- Apply everything, record `before` for each change in `company/onboarding/<run>/changes.json`; Undo per change and Undo all.
- Skills are written as project versions (mode `add`) for each chosen tracker project; general skills are never changed.
- Knowledge base `company/knowledge.md` (trimmed to 12,000 chars) is added to every step's system prompt; framework profile `company/profile.json` is added to the Create tests prompt.
- Clean UI: one screen, four steps, only decisions and status visible; details behind a click.
- Docs: update `docs/ARCHITECTURE.md` and `README.md` in the same commit as the feature.

## Review Focus

- A source is not connected or its token fails → that area is skipped and listed; the rest still runs and applies (test in Task 5).
- Claude returns malformed or partial JSON for one area → that area is reported failed; other areas apply (Task 3).
- The repo folder doesn't exist / clone fails / repo is huge (node_modules, binaries) → clear message; heavy folders skipped; cap respected (Task 2).
- Undo after the user edited the same skill or setting again since onboarding → undo restores the onboarding `before` only if the current value is still onboarding's `after`; otherwise it reports "changed since" and leaves it (Task 4).
- Study started twice at once / app restarted mid-study → second start refused while running; on restart an unfinished run is marked stopped, finished areas kept (Task 5).

---

### Task 1: Recent ticket samples from every tracker

**Files:**
- Modify: `qa_app/workflow/clients.py` (RealJira, MockJira), `qa_app/integrations/jira.py`, `qa_app/integrations/atlassian_mcp.py` (McpJira), `qa_app/integrations/azure_boards.py` (AzureBoards)
- Create: `qa_app/onboarding/__init__.py`, `qa_app/onboarding/collect.py` (`brief_ticket`)
- Test: `tests/test_onboarding_collect.py`

**Interfaces:**
- Produces: `client.recent(project: str, limit: int = 200) -> list[dict]` on RealJira, McpJira, AzureBoards, MockJira, newest first; raw items normalised by `collect.brief_ticket(raw: dict) -> dict` with keys `key, title, type, status, priority, components, labels, description (≤2000 chars), comments (last 5, each ≤400 chars)`.

- [ ] Test `test_recent_tickets_are_newest_first_and_brief` (MockJira with 3 issues; `recent("OPTR", 2)` returns 2 dicts with exactly the keys above, newest `updated` first).
- [ ] Test `test_jira_rest_recent_pages_through_search` (fake session: two pages of 100, `limit=150` → 150, JQL `project = "SCRUM" ORDER BY updated DESC`).
- [ ] Run, see them fail. Implement: REST via `/rest/api/3/search/jql` (fields `summary,issuetype,status,priority,components,labels,description,comment,updated`); MCP via `searchJiraIssuesUsingJql` with the same fields, paging with `nextPageToken` or `startAt`; Azure via WIQL (`[System.TeamProject] = @project ORDER BY [System.ChangedDate] DESC`) + `workitemsbatch`; descriptions through `ticket_context.text`.
- [ ] Run, pass. Commit.

### Task 2: Collectors

**Files:**
- Modify: `qa_app/onboarding/collect.py`; `qa_app/integrations/testrail.py` (`recent_cases`)
- Test: `tests/test_onboarding_collect.py`

**Interfaces:**
- Consumes: Task 1 `recent`; `testrail.resolve`, `testrail.section_paths`; `confluence.for_jira(...)` readers (`search`, `page`); `confluence.PAGE_URL`.
- Produces:
  - `collect_tracker(client, projects: list[str], limit=200) -> dict` → `{"tickets": [...], "statuses": [...], "components": [...], "labels": [...], "types": [...], "transitions": {status: [names]}}` (lists derived from the sample; transitions read from one ticket per status).
  - `testrail.recent_cases(cfg, limit=150) -> list[dict]` (`id, title, section, steps, expected, type, priority`); `collect_testrail(cfg, limit=150) -> dict` → `{"sections": [paths], "cases": [...]}`.
  - `collect_confluence(reader, ticket_texts: list[str], spaces: list[str], limit=30) -> dict` → `{"pages": [{title,url,text}]}` (pages linked from tickets first, then latest in the chosen spaces).
  - `collect_repo(source: str, workdir: Path) -> dict` → `{"root", "tree": [paths ≤3000], "files": {path: text}, "skipped": [...]}`; `source` is a folder path or a git URL (cloned depth 1 into `workdir/<name>`); skips `node_modules, .git, venv, .venv, dist, build, __pycache__, coverage, test-results, playwright-report`; picks manifests/configs/CI/README first, then specs/page objects/helpers/fixtures (most recent + one per folder), stopping at 120,000 chars.
- [ ] Tests: `test_repo_collector_finds_framework_files_and_skips_heavy_folders` (tmp repo with package.json, playwright.config.ts, tests/a.spec.ts, pageObjects/login.ts, node_modules/x.js → node_modules absent, configs present, cap respected); `test_missing_repo_folder_is_a_clear_error`; `test_testrail_collector_reads_sections_and_cases` (fake client); `test_confluence_collector_prefers_linked_pages`.
- [ ] Run, fail. Implement. Run, pass. Commit.

### Task 3: Analysis

**Files:**
- Create: `qa_app/onboarding/analyze.py`
- Test: `tests/test_onboarding_analyze.py`

**Interfaces:**
- Consumes: `agent.ask_claude(cfg, system, prompt, max_tokens)`, `agent._json_block`.
- Produces: `async analyze(cfg, collected: dict, on_event) -> dict` returning
  `{"tickets": {...} | None, "testrail": {...} | None, "knowledge": {...} | None, "repo": {...} | None, "failed": {area: reason}}` where
  - tickets: `{"settings": {"jira_column"?, "fe_components"?: [..], "be_components"?: [..], "env_hints"?: [..]}, "move_rules": {"passed"|"failed"|"incomplete": state}, "skills": {"gather": md, "jira-comment": md}, "evidence": [str]}`
  - testrail: `{"skills": {"testrail": md}, "section_map": {component_or_area: section_path}, "evidence": [str]}`
  - knowledge: `{"markdown": md, "evidence": [str]}`
  - repo: `{"profile": {"language","framework","runner","test_dir","file_pattern","page_objects","helpers":[..],"auth","run_command","ci_command","results"}, "skills": {"create-tests": md}, "evidence": [str]}`
  Tickets are analysed in batches of 50 (observations), then one combine call. Each area failing (exception or bad JSON) goes to `failed` and doesn't stop the others.
- [ ] Tests with a scripted `ask_claude`: `test_tickets_are_read_in_batches_then_combined` (120 tickets → 3 batch calls + 1 combine); `test_a_bad_answer_fails_only_that_area`; `test_each_area_returns_its_contract`.
- [ ] Run, fail. Implement. Run, pass. Commit.

### Task 4: Apply and undo

**Files:**
- Create: `qa_app/onboarding/apply.py`
- Modify: `qa_app/workflow/move_rules.py` use only; `qa_app/workflow/skills.py` use only
- Test: `tests/test_onboarding_apply.py`

**Interfaces:**
- Produces: `plan(findings: dict, projects: list[str]) -> list[dict]` (each change `{id, kind: "setting"|"skill"|"move_rule"|"file", target, label, after, evidence}`); `apply(changes, run_dir: Path) -> list[dict]` (adds `before`, `replaced_edit`, writes, saves `changes.json`); `undo(run_dir, change_id) -> str` ("undone" | "changed since"); `undo_all(run_dir) -> dict`.
  Targets: settings `"workflow.<key>"` / `"testrail.section_map"`; skills `"<PROJECT>/<step>"` (project version, mode add); move rules `"move_rule.<result>"` (in the general jira-comment skill via `move_rules.with_rule`); files `"company/knowledge.md"`, `"company/profile.json"`.
- [ ] Tests: `test_apply_writes_everything_and_records_before`; `test_undo_restores_exactly`; `test_undo_after_your_own_later_edit_leaves_it` ("changed since"); `test_undo_all_restores_the_run`; `test_replacing_your_own_project_skill_is_marked`.
- [ ] Run, fail. Implement. Run, pass. Commit.

### Task 5: Study runs and use in the steps

**Files:**
- Create: `qa_app/onboarding/run.py`
- Modify: `qa_app/workflow/agent.py` (`system()` adds `company_context()`; Create tests prompt adds the profile), `qa_app/workflow/settings.py` (`company_dir`)
- Test: `tests/test_onboarding_run.py`

**Interfaces:**
- Produces: class `Onboarding(app_dir: Path, clients_factory)` with `state() -> dict`, `async study(choices: dict) -> str` (run id), `stop()`, `undo(change_id)`, `undo_all()`; publishes bus events `{"type": "onboarding", "event": "progress"|"line"|"done", ...}`; `choices = {"projects": [..], "spaces": [..], "repo": str, "testrail": bool}`; `agent.company_context(cfg) -> str` (knowledge, trimmed 12,000).
- [ ] Tests: `test_a_study_collects_analyses_applies_and_reports` (fakes for every source + scripted Claude → changes applied, summary lists them, events emitted); `test_a_missing_source_is_skipped_and_listed`; `test_only_one_study_at_a_time`; `test_knowledge_reaches_every_step_prompt`.
- [ ] Run, fail. Implement. Run, pass. Commit.

### Task 6: Screen, routes, docs

**Files:**
- Modify: `qa_app/web/server.py` (routes `GET /api/onboarding`, `POST /api/onboarding/study`, `POST /api/onboarding/stop`, `POST /api/onboarding/undo/{id}`, `POST /api/onboarding/undo-all`), `qa_app/web/static/app.js` + `app.css` (route `onboarding`, sidebar entry, first-run redirect when nothing is connected and no study exists), `docs/ARCHITECTURE.md`, `README.md`
- [ ] Screen: four steps in one card (Connect · Choose · Study · What changed); connection rows show connected/not with a link to the card; choices with defaults; Study shows a progress list and a collapsible live panel; What changed lists changes grouped by output with evidence on click, Undo per item, Undo all, Study again.
- [ ] Check in the preview (Playwright screenshot); run all suites; update docs; commit; push; deliver.

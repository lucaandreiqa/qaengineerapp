---
name: Gather requirements (OPTR)
mode: add
---
# For OPTR (EVA Suite Admin)

EVA Suite Admin specifics for OPTR tickets, taken word for word from the team's original skills. They add to the general skill above; where they are more specific, follow them. Where they ask you to fetch something yourself (Jira, gh, git, TestRail), use what YourQA already fetched in `<connected_apps>` instead, and list what is missing under Open questions.

## Gather context (personal_gather-context)

### Gather Context for Admin Suite Frontend Testing


#### Goal

To gather all information relevant for frontend (Admin Suite) testing of an implemented change. This includes understanding what changed, which Admin Suite pages and flows are affected, what EVA settings and services are involved, and what existing test coverage already exists in this project.


#### Input

Input for this skill can be either a Jira ticket, a prompt by the user describing a change, or a list of affected areas that need investigation.


#### Prerequisites

If the input is a Jira ticket, the Atlassian/Jira MCP Plugin is required to fetch ticket details. This skill runs Jira/PR-only -- it does not depend on the EVA Docs MCP or New Black QA MCP (not available/used in this project; API and settings documentation is instead pulled from the linked GitHub PR, and historic QA context from this project's own TestRail cases and existing specs).


#### Approach

1. **Interpret the input**
    1a. If the input is a Jira ticket, use the Atlassian MCP to fetch the ticket Title, full Description, and all Comments.
    1b. Identify the core change: is it a new feature, a bug fix, a UI redesign, a new setting, a new API property exposed in the UI, etc.

2. **Identify affected Admin Suite pages**
    2a. From the ticket description and comments, determine which Admin Suite module(s) and chapter(s) are affected (e.g., Control Room > Settings, Organizations > Companies).
    2b. Map these to the test directory structure in this project (`tests/<module>/<chapter>/`).
    2c. Check what existing automated tests already cover for those areas by reading the spec files.

3. **Identify related EVA API/settings surface**
    3a. From the ticket, its linked PR, and this project's own specs/helpers, determine relevant API services that the Admin Suite pages call.
    3b. Include relevant EVA Settings and App Settings that affect the UI behavior.
    3c. Note any new properties, flags, or options that the frontend needs to expose.

4. **Search for related QA context**
    4a. Check TestRail (via its API/MCP if connected) for existing manual test cases relevant to the change.
    4b. Apply this project's own established frontend testing heuristics (see other admin-suite-* skills).

5. **Identify impact dimensions for frontend testing**
    5a. UI states: what different states can the page be in (empty, loaded, error, permission-denied)?
    5b. Setting-dependent behavior: does the UI change based on EVA settings?
    5c. Permission-dependent behavior: do different user roles see different things?
    5d. Entity-type variations: does the same UI behave differently for different entity types (e.g., different device types, different reason types)?
    5e. Form validation: what fields are required, what formats are enforced?
    5f. Confirmation dialogs: are there impact dialogs, "Are you sure?" prompts?

6. **Assess existing automation coverage**
    6a. List existing spec files that cover the affected area.
    6b. For each, note what is already tested and what gaps exist.
    6c. If manual TestRail test cases exist for this area, cross-reference them with the automation.

7. **Extract deployment endpoints from the ticket**
    7a. Look in the ticket description and comments for the feature branch Admin Suite URL (e.g., `https://optr-12345--abc123.on-eva.io`). This is where the frontend change can be tested before it merges to develop.
    7b. Look for the feature branch API endpoint (e.g., `https://api.optr-12345.ci-cd.on-eva.io/`). This is needed for API calls during test execution.
    7c. If either URL is not found, STOP and ask the user to provide the deployment URLs before continuing. Do not write the context file without deployment URLs -- everything downstream depends on them.

8. **Output the context** in a new file at `tests/tickets/<ticket>/<ticket>-context.md` using the template from `assets/context-template.md`.


#### Rules

- The output is always in English.
- Do not use bulletpoints or emojis.
- Do not execute the Approach steps if the prerequisite check has not passed.
- Use the template found in `assets/context-template.md`.
- For Jira tickets, the About section must contain: (1) a short summary, (2) the full ticket description as written in Jira, (3) a summary of the comments with outcomes of discussions, (4) acceptance criteria only when the ticket explicitly contains them -- do not invent or infer acceptance criteria.
- When listing affected pages, use the Admin Suite navigation path (e.g., "Control Room > Endpoint Configurations > Detail page").
- When listing EVA services, include the service name and the specific properties relevant to the frontend change.
- When listing settings, note whether they affect UI visibility, form behavior, or page access.
- Always extract the feature branch deployment URLs from the ticket. These are critical for running the tests against the correct environment.


#### What not to do

- Do not invent or infer acceptance criteria.
- Do not assume which pages are affected without checking the ticket description and documentation.
- Do not skip checking existing test coverage in this project.

## Scenario remarks (personal_define-scenarios)

##### Remarks section (for findings that are not asserted as scenarios)

Append a `## Remarks` section to the bottom of `<ticket>-scenarios.md` (after `## Not automatable` and `## Data mutations`). Every finding from the UI-inspection step that is not turned into a scenario must appear here with three required fields and a reference to its evidence file in `tests/tickets/<ticket>/rejections/`.

```markdown

## Phase 1 (personal_test-ticket)

### Phase 1 -- Discovery and planning

1. **Gather context.** Follow the `personal_gather-context` skill exactly (Jira/PR-only -- this project does not use the EVA Docs MCP or New Black QA MCP). Produces `<ticket>-context.md`.
   - If it already exists and looks current (check for Jira comments newer than the file's content by re-fetching the ticket's comments), skip re-gathering and note that it was reused. If it looks stale, ask before deciding to regather or patch it.
   - **Frontend and Core tickets usually link a GitHub PR in the comments** (`new-black/eva-suite-admin` for Frontend, `new-black/eva` for Core). Always check it -- the PR's own commits carry implementation detail well beyond what the Jira description/comments state (exact hook/component names, deliberate exceptions, bugs fixed in passing, root causes of any follow-up fix commits). Pull this in as part of context-gathering, not as an afterthought:
     - If `gh` CLI is authenticated (`gh auth status` succeeds), use it directly (`gh pr view <number> --repo <org>/<repo> --comments`) to also get the PR's review-comment thread, not just commits.
     - Otherwise, fall back to plain git: identify the org/repo and PR number from the link, then `git fetch origin pull/<number>/head:<local-branch>` (works with the existing git credential, no `gh`/token needed) into a scratch directory (never the actual project working tree). Find the ticket's own commits with `git log --oneline <local-branch> | grep -i <ticket>` and inspect each with `git show <sha>` for the real diff and commit message. This surfaces commits and diffs, not the PR's review-comment thread -- note that distinction in the context file rather than presenting commit messages as if they were review comments.
     - Never extract or reuse a cached git/API credential for a purpose other than what it was already being used for (e.g. don't pull a token out of the git credential store to hit the GitHub API with it) -- if `gh` isn't authenticated and the git-fetch fallback isn't enough, ask the user rather than working around it.
     - Record concrete findings (real component/hook/file names, deliberate exceptions, regressions fixed in passing) directly in `<ticket>-context.md` and carry them into scenarios/checklist -- this is usually far more useful than the ticket's own often-vague reproduction notes.
2. **Classify the ticket and resolve the target environment.** Uses data already fetched in step 1 (Components, status, comments) -- no extra API calls needed.
   - **Ticket type**: check the ticket's Jira Components field. If it includes `Core`, this is a **Core (backend-only)** ticket -- no Admin Suite UI is expected until confirmed otherwise for the affected area. Otherwise it's a **Frontend** ticket -- Admin Suite UI is expected to be in scope.
   - **Environment for Core tickets** -- depends on the ticket's current Jira status:
     - Status `Open` or `Draft` (not yet merged): search the ticket's comments for an environment link matching the `https://pr-<number>.ci-cd.on-eva.io/` pattern -- a PR-specific backend deployment, distinct from the `optr-<ticket>`/`feature-optr-<ticket>` frontend pattern used below. Use that PR environment as the target for this session. If no such link is found in the comments, stop and ask rather than guessing or silently falling back to `euw`.
     - Status `Merged` (or further along -- released, done, etc.): the change should already be live on the shared `euw` test cloud. Target `euw`/`.env` defaults directly; no PR environment needed.
   - **Environment for Frontend tickets**: same principle as Core -- search the ticket's comments for a branch preview link. Frontend previews follow one of at least three known patterns: `https://feature-optr-<ticket>--euw.newblack.test.eva-online.cloud/` (paired API: the shared `https://api.euw.newblack.test.eva-online.cloud`, not a per-branch API -- see `personal_gather-context`); `https://optr-<ticket>--<hash>.on-eva.io` (paired API: `https://api.optr-<ticket>.ci-cd.on-eva.io/`); or `https://feature-optr-<ticket>.eva-suite-admin.pages.dev/` (Cloudflare Pages -- its paired API is not baked into the JS bundle, confirm live via browser network requests rather than assuming; the shared `euw` API is the working assumption pending that check). Treat this as a non-exhaustive list -- if the comments contain a link that's clearly a deployment preview for this ticket but doesn't match any known pattern, use it anyway and note the new pattern for this skill. Use whichever preview link is actually in the comments as the target for this session. If genuinely no preview link is found in the comments and the ticket is already merged, fall back to `euw`/`.env` defaults, same as a merged Core ticket -- but if it's unmerged with no preview link, stop and ask rather than guessing, exactly like the Core case above.
   - Record the classification (Core/Frontend) and the resolved target environment in `<ticket>-context.md`'s Deployment section, so Phase 2 doesn't have to re-derive it.
3. **Define scenarios.** Follow the `personal_define-scenarios` skill using the context just gathered. Produces `<ticket>-scenarios.md`.
4. **Build the QA checklist.** Derive checklist items from the scenarios (and the ticket's own "For QA" section if it has one -- treat that as the de facto priority order). Never invent items not traceable to the ticket, its linked PR, or the scenarios file. Group items under `## <Feature/area>` headers; number items **globally across the whole file**, not restarting per section. Write `<ticket>-qa-checklist.md` using this exact format (statuses left as ⬜ NOT TESTED until Phase 2 actually runs them):

   ```markdown
   # QA Checklist - <ticket>

   <One-line description of what's being tested (foundational context, e.g. "Worked hours data model, settings, and read service"). Reference `<ticket>-context.md` for full details. Call out anything intentionally out of scope for this checklist and why.>

   **Status legend:** ✅ PASS (automated) · ⚠️ PARTIAL (partly confirmed, caveat below) · ❌ FAIL (reproduced bug) · 🚫 BLOCKED (couldn't be exercised due to another bug) · ⬜ NOT TESTED (no automated coverage yet, reason given)

   Verified <date> against <environment/feature-branch> (<OU/account context>) via `<ticket>.spec.ts`<` and <ticket>.serial.spec.ts` if any>. See `<ticket>-context.md` for the raw findings this table is based on.

   <Optional bold callout block here for an environment blocker or important caveat that applies across multiple items -- state root cause, whether it's a product bug vs. environment/account gap, and what's needed to unblock, same level of detail as a bug writeup.>

   ## 1. <Feature/area name>

   1. ✅ **PASS** — <Verify statement, phrased like an AC/claim to check>. <Narrative evidence: exact values, requests/responses, or reason if not tested/blocked.>
   2. ⚠️ **PARTIAL** — <statement>. <what's confirmed, what isn't, and why>.

   ## 2. <Next feature/area name>

   3. ❌ **FAIL** — <statement>. <evidence>.
   ```

   This is a numbered list per item, not a table -- each item carries its own status marker and a narrative evidence sentence, not just a terse pass/fail. When a later re-test session changes an item's status, just update the marker and evidence in place -- do not append a `*(reclassified <date>; was <old status>)*` annotation. The checklist reflects current, live truth about the ticket; the history of how it got there belongs in git history and the report file's dated sections, not inline clutter on every re-tested line. Cross-references to other tickets' checklists use `[[OPTR-XXXXX]]` -- this is an established convention in this repo's own checklist files, not something to avoid.

5. Confirm `<ticket>-context.md`, `<ticket>-scenarios.md`, and `<ticket>-qa-checklist.md` all exist under `tests/tickets/<ticket>/`.
6. **Stop. This is mandatory review gate #1.** Hand the checklist (and scenarios) to the user for review. Do not proceed to Phase 2 in the same turn, regardless of how confident the derived items are. State plainly that no tests have been executed yet -- everything so far is a plan, not a result. Wait for the user to confirm before running or writing anything in Phase 2.

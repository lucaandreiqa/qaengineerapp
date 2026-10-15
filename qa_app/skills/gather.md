---
name: Gather requirements
description: Gather context, define scenarios and build the QA checklist (the team's gather-context, define-scenarios and test-ticket phase 1 skills).
---
# Gather requirements

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

## Define scenarios (personal_define-scenarios)

### Define Frontend Test Scenarios for Admin Suite


#### Goal

To produce a list of testable frontend scenarios grouped per topic. Each scenario describes a specific user interaction in Admin Suite and its expected visual or behavioral outcome.


#### Input

Input can be a Jira ticket, a user prompt, a list of scenarios to be refined, or previously gathered context at `tests/tickets/<ticket>/<ticket>-context.md`.


#### Prerequisites

If the input is a Jira ticket, the Atlassian/Jira MCP Plugin is required to fetch ticket details. This skill does not depend on the EVA Docs MCP or New Black QA MCP (not available/used in this project).


#### Approach

1. **Interpret the input**
    1a. If a Jira ticket, fetch the Title, Description and Comments.
    1b. If context has been gathered at `tests/tickets/<ticket>/<ticket>-context.md`, use that file.
    1c. If scenarios are provided for refinement, start from those.

2. **Enumerate all states for each affected UI component (mandatory)**
    Before writing any scenarios, for each affected UI component or section:
    2a. List every possible state the component can be in (e.g., for an Endpoint section: has-endpoint, deleted-endpoint, never-had-endpoint).
    2b. List every possible action a user can take from each state (e.g., change endpoint, attach endpoint, view details).
    2c. Present this state/action matrix. For each valid state+action combination, a scenario must exist.
    2d. For any state that cannot be reproduced via the API (e.g., the API does not allow creating an entity without a required field), note it as "not automatable" with the reason. These go in a separate "Not automatable" section at the bottom of the scenarios file and must be mentioned in the final remarks.

3. **Determine the scenarios that should be verified**
    3a. For each affected Admin Suite page, identify the user flows to test.
    3b. Apply the one-test-one-concern principle: each scenario tests exactly one behavior.
    3c. Break down combined flows into individual scenarios:
        - CRUD operations become separate create, read, update, delete scenarios
        - Form validation becomes separate required-field and format-validation scenarios
        - Permission checks become separate scenarios per role
        - Setting-dependent behavior becomes separate scenarios per setting state
    3d. When the context includes entity-type variations (e.g., different reason types, different device types), generate scenarios for every in-scope type where behavior differs. If all types share the same behavior, one parameterized scenario is sufficient.
    3e. When the context includes a scenario checklist, produce at least one scenario for every item. Do not collapse or omit items.
    3f. For each scenario, specify the expected visual outcome (what the user sees, what appears on screen) rather than internal API responses.
    3g. If the ticket lists acceptance criteria, include those as scenarios in a dedicated topic.

4. **Classify each scenario by test type**
    - **Happy path**: The main user flow works as expected
    - **Validation**: Required fields, format errors, business rule violations
    - **Error handling**: What happens when an API call fails (e.g., save returns an error), when the network is slow, or when the page shows a loading state
    - **Permission**: Different roles see different UI or are blocked
    - **Setting-dependent**: UI changes based on EVA setting values
    - **Edge case**: Empty states, large datasets, special characters
    - **Data verification**: After an action, verify ALL visible data on the page, not just one field (e.g., after re-attaching an endpoint, verify the endpoint name, URL, and status are all correct)
    - **Adjacent flows**: Can other operations still work when the entity is in an unusual state (e.g., can you still edit a webhook name when its endpoint is deleted)
    - **Regression**: Existing functionality that should not break

5. **If things are unclear or the expected outcome is unknown, ask for additional input.**

6. **Output the scenarios** in `tests/tickets/<ticket>/<ticket>-scenarios.md`.


#### Scenario Format

##### Statement-style (for linear user flows)

A single sentence that can be answered with true or false:

```
After creating a new endpoint configuration with name "Test EC", the detail page shows the configuration with the correct name and endpoint URL.
```

```
When an employee without edit permissions opens a setting detail page, a blue alert bar shows "You can view this setting but cannot edit it due to insufficient permissions."
```

##### Table-style (for variations across types or dimensions)

Use when the same flow applies to multiple entity types or setting combinations:

```
| Reason type | Can create | Can edit name | Can edit description | Requires OU |
|-------------|-----------|---------------|--------------------|----|
| Open cash drawer | yes | yes | yes | no |
| Tax exemption | yes | yes | yes | yes |
| Organization return | yes | yes | yes | yes |
```

##### Remarks section (for findings that are not asserted as scenarios)

Append a `## Remarks` section to the bottom of `<ticket>-scenarios.md` (after `## Not automatable` and `## Data mutations`). Every finding from the UI-inspection step that is not turned into a scenario must appear here with three required fields and a reference to its evidence file in `tests/tickets/<ticket>/rejections/`.

```markdown
## Remarks

### R3 - Translations modal has no filter funnel button
- Steps to reproduce:
  1. Open a Discount detail page that has a Discount image uploaded.
  2. On the Display options tab, click the translation icon on the Discount image.
- What is wrong:
  The Translations modal header renders only the "+" action; the design (Figma) shows a filter funnel button next to it. Locked in as current behaviour but flagged for the PM.
- Evidence:
  - rejections/R3-translations-modal-header-no-funnel.png
  - rejections/R3-modal-header-no-funnel.yaml  (optional snapshot)
```

Rules for remarks:
- Every remark gets a `### R<N> - <title>` heading. The number `<N>` is the same number used as the prefix of the corresponding `R<N>-<slug>.{png,yaml}` files in `tests/tickets/<ticket>/rejections/` and as the block heading in the QA Notes Remarks section.
- `Steps to reproduce` (numbered list), `What is wrong` (1-2 sentences), and `Evidence` (relative paths into `rejections/`) are mandatory subsections.
- Evidence paths are relative to the ticket folder so they resolve from `<ticket>-scenarios.md`.
- One evidence file may cover several remarks via a combined slug (for example `R2-R9-R11-translations-modal-full.png`); list it under every remark it supports.


#### Rules

- The output is always in English.
- Every scenario describes what the user does and what they should see. Not what the API returns.
- A scenario is a single-sentence statement that can be verified by looking at the screen.
- Expected outcomes must be concrete and observable: "the detail page shows the monitor name" not "the monitor is created successfully."
- When a scenario involves navigation, state where the user ends up: "the employee is redirected to the overview page" or "the detail page is shown with the updated value."
- When a scenario involves a dialog, state what the dialog shows: "a confirmation dialog lists the 3 affected stores."
- Do not use vague outcomes like "works correctly" or "behaves as expected."
- Each scenario must map to exactly one automated test. If a scenario would require multiple assertions about different behaviors, split it.
- Do not merge distinct scenarios. Each behavior is its own scenario.
- Prefer exhaustive coverage of variations over a small sample.
- Always include ALL possibly impacted flows, not just the happy path. If a change introduces a new state (e.g., "deleted endpoint"), also cover adjacent states that share the same UI area (e.g., "never-had-endpoint", "has-endpoint"). All states of the same component must be tested.
- Always include everything mentioned in the ticket, including comments. If a comment asks for additional improvements (e.g., "would be nice if we show a better error message"), include scenarios for those too.
- Group scenarios by topic (CRUD, Validation, Permissions, etc.) for readability.
- Any UI-inspection finding (from the `test-ticket` workflow Step 3) that is not asserted as a scenario must instead be captured in the `## Remarks` section using the `### R<N> - <title>` template, with **steps to reproduce**, **what is wrong**, and **evidence** files saved to `tests/tickets/<ticket>/rejections/R<N>-<slug>.{png,yaml}`. The remark numbering must match the file prefixes so the QA Notes posting can attach the right images.
- A good example can be found in `references/good-scenarios.md`.


#### What not to do

- Do not assume expected outcomes; verify or ask when unclear.
- Do not add Priority or Type metadata to scenarios.
- Do not produce vague outcomes that cannot be verified by looking at the screen.
- Do not combine multiple behaviors into one scenario.
- Do not omit scenarios when the context provides a checklist; every item must be covered.
- A list of bad examples can be found in `references/bad-scenarios.md`.

## End-to-end workflow, phase 1 (personal_test-ticket)

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

### Rules

- Each phase's confirmation is independent. Approving the checklist/scenarios does not approve every result unconditionally; approving the Jira comment does not approve the transition; approving the transition does not approve pushing TestRail cases. Never chain approvals across phases.
- All four mandatory review gates apply unconditionally, including when auto mode or any other session-level "proceed without asking" default is active. This skill's gates override that default -- they are not something auto mode's general bias supersedes.
- The checklist review gate (Phase 1, step 6) is mandatory even when the ticket seems simple or the checklist seems obviously correct.
- Ticket-type classification (Phase 1, step 2) happens before scenarios/checklist, since it determines which environment everything downstream targets. Don't build the checklist or spec against an assumed environment -- always resolve it explicitly first.
- Never invent checklist items, scenarios, acceptance criteria, or test results not traceable to the ticket, its linked PR, or what was actually executed live this session.
- If the ticket already has some of these files from a prior session, reuse and extend them rather than overwriting blindly -- check what exists first.
- Settings cleanup is unconditional -- revert every mutated setting regardless of test outcome, and do it in Phase 2 itself, not deferred to after mandatory review gate #2.
- Default to `andrei.luca@red-to-blue.com` / OU `lucatestaustriastore` for any test account/session; only deviate with a stated, scenario-tied reason.

### What not to do

- Do not proceed to Phase 2 in the same turn the checklist is written -- always stop and wait for the user's review first.
- Do not skip Phase 2's actual spec build-and-run and jump straight to writing checklist results -- every status other than ⬜ NOT TESTED/🚫 BLOCKED must come from something actually run this session.
- Do not post the Jira comment or transition the ticket without showing the exact content/target state first.
- Do not push TestRail cases as an automatic continuation of Phase 3's approvals -- it always needs its own explicit go-ahead, given separately.
- Do not fuzzy-match a Jira transition name if the exact target state isn't available from the current status -- stop and report what is available instead.
- Do not assume either ticket type's environment. If it's unmerged and no preview link (`pr-<number>.ci-cd.on-eva.io` for Core, `feature-optr-<ticket>--euw...`/`optr-<ticket>--<hash>.on-eva.io` for Frontend) is findable in the comments, stop and ask -- do not fall back to `euw` silently, since the change may not exist there yet.
- Do not leave a mutated setting unreverted because the run ended, the ticket is done, or the bug was already found -- revert and verify every time.
- Do not substitute a different test account/OU than the default without a reason tied to the specific scenario's needs.

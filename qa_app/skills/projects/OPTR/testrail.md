---
name: Update TestRail tests (OPTR)
mode: add
---
# For OPTR (EVA Suite Admin)

EVA Suite Admin specifics for OPTR tickets, taken word for word from the team's original skills. They add to the general skill above; where they are more specific, follow them. Where they ask you to fetch something yourself (Jira, gh, git, TestRail), use what YourQA already fetched in `<connected_apps>` instead, and list what is missing under Open questions.

### Phase 4 -- TestRail cases (draft now, push only later)

This phase follows `admin-suite-testrail-add-cases` exactly -- do not shortcut its two-phase discipline just because it's the tail end of one larger workflow.

16. **Draft cases** based on the checklist's confirmed (✅ PASS) items -- one case per distinct concern, matching this project's one-test-one-concern convention (see `admin-suite-testrail-migration` for how manual tests map to focused cases). Determine the target TestRail section, check for an existing template style or Finance-section conventions, check for duplicates -- all read-only. Write `<ticket>-testrail-cases.md`.
17. **Stop. This is mandatory review gate #4.** Tell the user the draft is ready for review. Do not call `add_case`/`add_section` in this phase, no matter how confident the cases are or how much confirmation happened earlier in this same run -- Phase 3's approvals do not carry forward to TestRail writes.
18. **Only push on a separate, later, explicit instruction** (e.g. "push these", "push to TestRail now") -- follow `admin-suite-testrail-add-cases` Phase 2 exactly, including: re-reading the draft fresh, re-verifying section/duplicates, verifying via `get_cases` before ever retrying a call that returned an error (TestRail's `add_case` has been observed to error in the response while still creating the case), and treating any later edit/merge/delete instruction as a local-draft-only change unless it comes with its own separate, explicit push instruction.

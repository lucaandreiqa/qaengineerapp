---
name: Update TestRail tests
description: Turn the passing checklist items into reusable TestRail cases (YourQA's case guidance plus the team's test-ticket phase 4 skill).
---
# Update TestRail tests

You turn the checklist items that passed into TestRail test cases that someone can run again later, without reading the ticket.

## Each case
- **Title**: the behaviour, as in the checklist item, without the ticket key ("Search ignores letter case").
- **Steps**: numbered, concrete, starting from a known state ("1. Sign in as a user with the export permission. 2. Open Reports › Worked hours. 3. …"). Include the test data to use.
- **Expected**: what must be true at the end, observable by a tester.
- FE cases describe UI actions; BE cases describe the request (method, endpoint, key fields) and the expected response.

## Rules
- Only items that passed. Partial, failed and blocked items do not become cases.
- One case per behaviour. Merge items that test the same thing; do not repeat a case that already exists in the section (you will get their titles).
- Keep ticket-specific test data out of the title; put it in the steps.

## End-to-end workflow, phase 4 (personal_test-ticket)

### Phase 4 -- TestRail cases (draft now, push only later)

This phase follows `admin-suite-testrail-add-cases` exactly -- do not shortcut its two-phase discipline just because it's the tail end of one larger workflow.

16. **Draft cases** based on the checklist's confirmed (✅ PASS) items -- one case per distinct concern, matching this project's one-test-one-concern convention (see `admin-suite-testrail-migration` for how manual tests map to focused cases). Determine the target TestRail section, check for an existing template style or Finance-section conventions, check for duplicates -- all read-only. Write `<ticket>-testrail-cases.md`.
17. **Stop. This is mandatory review gate #4.** Tell the user the draft is ready for review. Do not call `add_case`/`add_section` in this phase, no matter how confident the cases are or how much confirmation happened earlier in this same run -- Phase 3's approvals do not carry forward to TestRail writes.
18. **Only push on a separate, later, explicit instruction** (e.g. "push these", "push to TestRail now") -- follow `admin-suite-testrail-add-cases` Phase 2 exactly, including: re-reading the draft fresh, re-verifying section/duplicates, verifying via `get_cases` before ever retrying a call that returned an error (TestRail's `add_case` has been observed to error in the response while still creating the case), and treating any later edit/merge/delete instruction as a local-draft-only change unless it comes with its own separate, explicit push instruction.

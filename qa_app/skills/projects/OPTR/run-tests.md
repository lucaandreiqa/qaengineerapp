---
name: Run tests (OPTR)
mode: add
---
# For OPTR (EVA Suite Admin)

EVA Suite Admin specifics for OPTR tickets, taken word for word from the team's original skills. They add to the general skill above; where they are more specific, follow them. Where they ask you to fetch something yourself (Jira, gh, git, TestRail), use what YourQA already fetched in `<connected_apps>` instead, and list what is missing under Open questions.

### Cleanup (ALWAYS)

Every setting mutated during a test run must be reverted back to its original value before Phase 2 ends -- no exceptions, regardless of whether the run found a bug, the ticket is Core or Frontend, or the environment is shared (`euw`) or an ephemeral PR/preview environment.

- Before mutating any setting, read and note its current value first (via `GetSetting` or equivalent) -- this is what "original" means when reverting, not an assumption of the documented default.
- After the run (pass, fail, or blocked), revert every mutated setting back to that noted value, not just the ones that happen to matter for the final result.
- Record the revert in the checklist/report per item: what was changed, what it was reverted back to, and confirmation the revert was verified (re-read the setting, don't just assume the revert call succeeded).
- The same applies to test data and accounts: if something can be deleted/cleaned up (e.g. a created consumer, a throwaway OU set), clean it up. If it can't be deleted (e.g. orders, minted PINs/QR codes -- no delete capability exists), say so explicitly and flag what was left behind, per this repo's existing convention (see e.g. OPTR-48129's checklist).
- This is not conditional on mandatory review gate #2 -- do the cleanup and the recording of it as part of Phase 2 step 12, before handing anything to the user for review at that gate.

### Phase 2 -- Build, run, and report

7. **Build the spec.** Follow `admin-suite-build-tests` (and `personal_test-specs`/`admin-suite-page-objects`/`admin-suite-helpers` for any missing page objects or helpers) to turn the confirmed scenarios into `<ticket>.spec.ts`, splitting into `<ticket>.serial.spec.ts` for any scenario needing serial/multi-user execution, per this project's conventions.
8. **Run it** against the environment resolved in Phase 1 step 2 -- the PR environment for an unmerged Core ticket, `euw` for a merged Core ticket, or the feature-branch/`euw` resolution for a Frontend ticket. Do not re-derive this; use what step 2 already recorded in `<ticket>-context.md`. When using a shared environment (`euw`), follow this repo's shared-environment convention (confirm before mutating sensitive settings, revert after) rather than an ephemeral-PR-environment convention.
9. **Update the QA checklist with real results** from the run -- exact statuses, evidence (status codes, error types/messages, before/after state), and reclassification notes if this supersedes an earlier status. Never mark something other than ⬜ NOT TESTED/🚫 BLOCKED without it having actually run.
10. **If a bug is found**, document it in a dedicated subsection below the relevant checklist item: setup, exact repro steps/requests, raw results, analysis, severity, and a recommendation -- mirror the level of detail in prior tickets' checklists (full request/response bodies, not just "it failed").
11. **Write `<ticket>-report.md`**: a Summary paragraph (pass/fail counts, bugs found, anything blocked) plus a "What was tested" section mirroring the checklist. Standard for every ticket run through this skill.
12. **Clean up.** Follow the "Cleanup (ALWAYS)" section above -- every mutated setting reverted and verified, test data/accounts cleaned up where possible, everything recorded in the checklist or report.
13. **Stop and hand the updated checklist and report to the user for review.** This is mandatory review gate #2 -- do not proceed to Phase 3 in the same turn, and do not touch Jira at all yet. State the results plainly (counts, bugs, blocked items) and wait for explicit confirmation before posting anything or transitioning the ticket.

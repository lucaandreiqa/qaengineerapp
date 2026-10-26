---
name: Create tests
---
# Create tests

You write the Playwright Test spec (TypeScript) for the approved checklist. Specs are direct and readable: constants for test data, user-facing locators, inline API calls for setup and verification, and a clear arrange, act, assert flow in every test. YourQA saves and runs the spec; you do not run it here.

The skills under this one hold the detail: **Spec conventions**, **Locators and page structure**, **Test data, records and settings** and **UI updates and timing**.


## Before you write

1. **Take names from the code.** When `<connected_apps>` has the pull request, read its changed files and diffs. Component names, labels, routes, API service names, field names and enum values come from there, not from guesses. One wrong field name gives a silent empty or 400 response and wastes a whole run.
2. **Check each entity type on its own.** Different types can have different form fields, validation and payloads. Never generate a batch of tests on an assumed common layout.
3. **Use only what you know exists.** You cannot open the workspace. Use plain `@playwright/test` APIs unless the company's style examples (from onboarding) show helpers or page objects; then copy their patterns into the spec rather than importing from the company's repository.
4. **Every scenario becomes a test or a reason.** Confirm the starting state of each item can be created through the API or the UI. When it cannot, do not fake it (no navigating to made-up IDs); leave a comment where the test would be, saying why it is not automatable. When only part of an item can be automated, automate that part and comment what is not covered.


## What YourQA expects back

- One TypeScript file, nothing else around it.
- One test per checklist item, its title starting with the item number in brackets: `test('[3] Search ignores letter case', …)`.
- Partial or blocked outcomes reported through annotations (see Spec conventions).
- Every setting a test changes reverted, re-read and recorded in the cleanup file (see Test data, records and settings).
- Every piece of test data prefixed with the ticket key.


## Check your spec before returning it

- Every checklist item has exactly one test, or a comment saying why it is not automatable.
- Every step's description matches what its assertions check.
- No fixed sleeps, no CSS utility classes or generated IDs in locators, no unconfirmed `.first()`.
- Records the test created are found by their unique name, never by position.
- No test depends on another having run first.
- Nothing is deleted for cleanup, except where the deletion is what the test verifies or the record crowds a small paginated grid.

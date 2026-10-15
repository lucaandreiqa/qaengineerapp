---
name: Create tests
description: Write the Playwright spec for the approved checklist on any web app (from the team's test-specs and test-ticket skills).
---
# Create tests

You write the Playwright Test spec for the approved checklist. Specs are direct and readable: constants for test data, user-facing locators, inline API calls for setup and verification, and clean Arrange-Act-Assert flows. A project can add its own conventions (page objects, helpers, describe tags, auth helpers) as a project version of this skill; follow them when present.


## Before you write

1. **Use what the change really is.** When `<connected_apps>` contains the PR, read its changed files and diffs. Take component names, labels, routes, API service names, field names and enum values from the code, not from guesses. A single wrong field name causes a silent `{}` or `400` response that wastes a whole run.
2. **Do not assume similar entities share the same structure.** Different entity types can have different form fields, validation and API payloads. Check each type in the PR, the ticket or the Confluence pages before writing tests for several types. Never generate a batch of tests on an assumed common form layout.
3. **Use only helpers you know exist.** You cannot open the workspace. Use plain `@playwright/test` APIs unless the project version of this skill names helpers or page objects to import.


## File and structure

YourQA saves the spec as `tests/tickets/<KEY>/<KEY>.spec.ts`, and a `<KEY>.serial.spec.ts` when scenarios must run one at a time (multi-user, or changing settings that affect other tests).

```ts
import { test, expect } from "@playwright/test";

// Test data
const PREFIX = "PROJ-123";

test.describe("<Area> - <Feature> - <Topic>", () => {
  test("[1] Employee can create a new setting", async ({ page, request }) => {
    // ...
  });
});
```

- One checklist item is exactly one test. Its title starts with the item number in brackets, `[3] …`, so results map back to the checklist.
- Keep the checklist order. `test.describe` per section is fine.
- Use the base URL YourQA gives you; never hard-code another environment.
- The signed-in session (storage state) is preloaded by YourQA for the test account. Sign in manually only when a test needs a different user for a permission scenario.


## Test data

- Use simple constants for stable values (names, OU names). Do not hard-code entity IDs: look them up through the API, or use the human-readable name.
- Data that must be unique per run gets a random suffix, and every record a test creates gets a traceable name that ties it to the ticket: `` `PROJ-123 webhook ${random}` `` rather than a bare random string. The suffix keeps reruns from colliding; the prefix makes leftover data easy to find.


## API calls in tests

Write API payloads inline in the test with the `request` fixture, so the payload is visible where it matters. Arrange data through the API when possible; it is faster and more reliable than clicking through setup. Extract a helper only when the same call with the same payload appears in many tests and parsing it is non-trivial.


## Test patterns

- **Create**: navigate and open the form, fill and submit, assert the UI shows the created entity, verify through the API.
- **Update**: create the entity through the API, edit it in the UI, assert the UI reflects the change, verify through the API.
- **Delete**: create through the API, delete in the UI, assert where the user ends up (for example back on the overview).
- **Validation**: UI only; submit without required fields, assert the user stays on the form and the validation message is visible.
- **Request interception**: to verify what the UI sends, arm `page.waitForRequest(...)` before triggering the action, then check `request.postDataJSON()`.


## Records and cleanup

- **Do not delete the records a test creates.** No delete calls in `afterEach` and no cleanup step that deletes test data. Every record has a unique, traceable name instead.
- The only time a test deletes a record is when deletion is the behaviour under test; then the delete is the action, asserted like any other.
- **Exception: rows in a small paginated overview grid.** Leftover rows eventually push new ones past the first page and break other tests. For those, API teardown in `test.afterEach` is expected: register the name (not only the ID) so a test that fails early is still cleaned up; never fail the test from teardown; log teardown errors (`console.warn`) rather than swallowing them; respect delete ordering when references exist.
- **Settings are different: revert them.** Before changing a setting, read and note its current value. After the test (pass, fail or blocked), set it back to that noted value and read it again to prove it was restored. Append each one as a JSON line `{name, value, reread}` to the file in `process.env.QA_CLEANUP_FILE`.
- Data that cannot be deleted (orders, payments, audit entries) stays, prefixed with the ticket key; note it in a comment.


## Test steps

Use `test.step()` to group actions into named phases, so the report shows which phase failed.

- Name steps by what they do: "Setup: create the setting via API", "Navigate to Settings and open the create form", "Fill in the form and submit", "Assert the detail page shows the correct values", "Verify through API that the value was persisted".
- **A step's description must match its assertions.** If a step says "Verify the error result is displayed", it must assert error-specific content, not just that a Done button appeared. If you would be surprised by what the assertions check after reading only the description, fix one of them.
- Do not wrap a single line in a step, do not use steps in teardown, and declare page objects and test data before the first step.


## Setting-dependent tests

When a test toggles a setting that changes UI behaviour, put it in the serial spec, use `test.describe.configure({ mode: "serial" })`, set the value in `beforeEach` and revert it in `afterEach` (recording it in the cleanup file).


## Outcomes other than pass and fail

- Something only partly works: `test.info().annotations.push({ type: "qa-result", description: "partial" })` with a short reason.
- The test cannot run (missing data, missing permission, environment down): `description: "blocked: <reason>"`, then stop the test.


## What to avoid

- Data builder functions and custom fixtures (`test.extend`): use constants and inline values.
- Hard-coded entity IDs.
- CSS chains and XPath: prefer `getByRole`, `getByLabel`, `getByText`, `getByTestId`, scoped to a container when needed.
- `waitForTimeout` and fixed sleeps: wait on deterministic signals (text appearing, a dialog closing, a response arriving).
- Tests that depend on execution order: each test must run on its own.
- Conditional workarounds for unexpected UI: never add try/catch to dismiss popups or checks for dialogs that "might" appear. Unexpected UI is a configuration or environment problem to report, not to hide.


## Running and failures

YourQA runs the spec and shows the output live; you do not run it here. When writing, avoid the common failure patterns:

- **Strict mode violations** ("resolved to 2 elements"): use `{ exact: true }`, scope to a container, or use `getByRole("heading", …)` instead of `getByText(…)`.
- **Element type changes**: a control can be a button in one state and a link in another.
- **Toast and message text** may differ from what a manual test document says; take it from the code or the ticket.
- **Timing after uploads or API calls**: wait for a deterministic signal before the next action.
- **Dialogs after save, create or delete**: wait for the mutation response, assert it succeeded, then assert the dialog is hidden; do not rely on `toBeHidden` alone.
- **Clickable rows without links**: assert the navigation to the detail page happened before asserting detail content.
- **Restricted pages** may hide the normal detail layout: wait for the route or the permission message.


## Test account

Use the test account and OU set in YourQA. Use a different account or OU only when a scenario needs it (a permission the default account lacks, or a multi-user scenario), and say why in a comment.

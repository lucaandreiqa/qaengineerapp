---
name: Spec conventions
parent: create-tests
---
# Spec conventions

## File and structure

YourQA saves the spec as `tests/tickets/<KEY>/<KEY>.spec.ts`, plus `<KEY>.serial.spec.ts` for tests that must run one at a time (more than one user, or settings that change what other tests see).

```ts
import { test, expect } from "@playwright/test";

// Test data
const PREFIX = "PROJ-123";
const ORGANIZATION_UNIT = "Main store";

test.describe("<Area> - <Feature> - <Topic>", () => {
  test("[1] Employees can create a webhook", async ({ page, request }) => {
    // arrange, act, assert
  });
});
```

- One checklist item is exactly one test, titled `[<item number>] <capability statement>`. Capability statements start with the actor: "Employees can…", "Employees cannot…", "If <condition>, …".
- Keep the checklist order. One `test.describe` per checklist section works well.
- Use the base URL YourQA gives you. Never hard-code another environment.
- The signed-in session for the test account is preloaded. Sign in manually only when a test needs another user, for a permission or multi-user scenario.
- Write full names in variables: `endpointConfigurationId`, not `ecId`.


## The flow of a test

Prefer: set up through the API, act through the UI, verify in the UI and through the API.

- **Create**: open the form, fill it in and submit, assert the UI shows the created entity, verify through the API.
- **Update**: create the entity through the API, edit it in the UI, assert the UI shows the change, verify through the API.
- **Delete**: create through the API, delete in the UI, assert where the user ends up, verify through the API that it is gone.
- **Validation**: UI only. Submit without the required fields; assert the user stays on the form and the message is visible.
- **What the UI sends**: arm `page.waitForRequest(...)` before triggering the action, then check `request.postDataJSON()`.

Write API payloads inline in the test with the `request` fixture, so the payload is visible as part of the test's intent. Extract a helper only when the same call with the same payload appears in many tests and reading its response is not trivial.


## Test steps

Group a test into named phases with `test.step()`, so the report shows which phase failed.

- Name steps by what they do: "Setup: create the setting through the API", "Open Settings and start a new setting", "Fill in the form and submit", "Assert the detail page shows the values", "Verify through the API that the value was saved".
- **A step's description is a promise about its assertions.** "Verify the error result is shown" must assert the error content, not only that a Done button appeared. If reading the description alone would surprise you about what the assertions check, fix one of them.
- Do not wrap a single line in a step, do not use steps in teardown, and declare test data and page helpers before the first step.


## Outcomes other than pass and fail

- Partly works: `test.info().annotations.push({ type: "qa-result", description: "partial" })` with a short reason.
- Cannot run (missing data, missing permission, environment down): `description: "blocked: <reason>"`, then stop the test.


## Parameterised tests

When the same behaviour applies to several entity types, generate the tests in a `for` loop over a constant array. Only when the types share exactly the same fields and behaviour; a type with an extra required field gets its own tests.


## Avoid

- Data builder functions and custom fixtures (`test.extend`) for small payloads: use constants and inline values.
- Hard-coded entity IDs: look them up through the API, or use the human-readable name.
- Tests that depend on running order. Each test must run on its own.
- Conditional workarounds for unexpected UI: no try/catch to dismiss popups, no checks for dialogs that "might" appear. Unexpected UI is a configuration or environment problem to report, not to hide.
- Skipping a scenario without a comment saying why.

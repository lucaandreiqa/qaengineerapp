---
name: Create tests (OPTR)
mode: add
---
# For OPTR (EVA Suite Admin)

EVA Suite Admin specifics for OPTR tickets, taken word for word from the team's original skills. They add to the general skill above; where they are more specific, follow them. Where they ask you to fetch something yourself (Jira, gh, git, TestRail), use what YourQA already fetched in `<connected_apps>` instead, and list what is missing under Open questions.

## Write test specs (personal_test-specs)

### Write Test Specs

This skill guides you through writing Playwright test specs for the EVA Suite Admin test automation project. Specs are direct and readable: constants for test data, page objects for UI interaction, inline API calls for setup and verification, and clean Arrange-Act-Assert flows.

#### Before you write tests

1. **Read the skeleton spec** if one exists — the user may have already outlined test cases with TODO comments describing each step
2. **Read the relevant page objects** — understand what actions and assertions are available
3. **Check available helpers** — see what utilities exist in `common/helpers.ts` (e.g., `generateRandomString`)
4. **If page objects don't exist yet**, create them first using the admin-suite-page-objects skill
5. **Do not assume similar entities have the same structure.** Different entity types (e.g., different reason types, different setting categories) may have completely different form fields, validation rules, and API payloads. Before writing tests for multiple entity types, verify the actual form fields and API fields for each type individually — either by inspecting the UI or by checking the API documentation. Never write a batch of tests assuming they all share the same Name+Description pattern or any other common form layout.
6. **Verify API service names, field names, and enum values before writing `callEvaApi` calls.** This project does not have the EVA Docs MCP available -- look up the API spec instead via the `new-black/eva` source (`gh api`/`gh pr view` if the ticket links a PR, or grep the service/request class directly) or by checking how an existing spec in this project already calls the same service. Pay attention to: exact property names (e.g., `PropertyType` vs `AddressRequirement`), enum values (e.g., Visibility accepts integers not strings), and required vs optional fields. A single wrong field name causes a silent `{}` or `400` response that wastes an entire debug cycle.
7. **Reference saved `tmp/snapshots/` files** from the page object inspection phase. If no snapshots exist, use `npx playwright cli` to inspect the UI before writing tests — especially for understanding what form fields, error messages, and success states look like.

#### File location

```
tests/<module>/<chapter>/<feature>.spec.ts
tests/<module>/<chapter>/<feature>.serial.spec.ts   # For tests that modify shared state (settings)
```

For example: `tests/control-room/settings/general.spec.ts`, `tests/control-room/api-users/general.spec.ts`

Use the `.serial.spec.ts` suffix when the test modifies EVA settings or app settings that affect other tests' frontend behavior. The suffix alone only serialises tests *within* the file. To also isolate the file from other workers, add its path to `ISOLATED_SPECS` in `playwright.config.ts` — that routes it to the `chromium-serial` project (single worker, runs after all regular tests, even if some failed).

#### Fixture file location

Test fixtures (certificates, CSV files, images, JSON data files, etc.) are stored in the `fixtures/` directory, organized by module:

```
fixtures/<module>/<fixture-file>
```

For example: `fixtures/control-room/test-certificate.pfx`

When a test needs a fixture, reference it with `path.resolve(__dirname, "../../../fixtures/<module>/<file>")`. Always place new fixtures in the module subfolder that matches the test that uses them.

#### Structure

Every spec file follows this layout:

```ts
import { test, expect } from "@playwright/test";
import { useAuthenticatedSession } from "../../../common/useAuthStorage";
import { callEvaApi } from "../../../common/helpers/api.helpers";
import { generateRandomString } from "../../../common/helpers";
import { OverviewPage } from "../../../pageObjects/module/chapter/overviewPage";
import { DetailPage } from "../../../pageObjects/module/chapter/detailPage";

// Test data
const OU_NAME = "Foundation AS - Bogus";

test.describe("Control Room - Settings - General - CRUD @regression @module-control-room @chapter-settings", () => {
  useAuthenticatedSession(test);

  test("Employee can create a new setting", async ({ page, request }) => {
    // ...
  });
});
```

#### Test describe format

The `test.describe` string follows this exact pattern:

```
<module> - <chapter> - <feature> - <topic> @regression @module-<module> @chapter-<chapter>
```

Examples:
- `"Control Room - Settings - General - CRUD @regression @module-control-room @chapter-settings"`
- `"Control Room - API Users - General - Validation @regression @module-control-room @chapter-api-users"`
- `"Control Room - Synchronization - General - File creation @regression @module-control-room @chapter-synchronization"`
- `"Control Room - Synchronization - Comparing - Sync flow @regression @module-control-room @chapter-synchronization"`

Tags must always include `@regression` and both `@module-<module>` and `@chapter-<chapter>`. Add `@smoke` for critical happy-path tests.

#### Test data

Use simple constants for entity names and OU names. Do **not** hardcode entity IDs — instead, look them up via API when needed or use only the human-readable names.

For test data that must be unique per run (like user names), use the `generateRandomString` helper:

```ts
import { generateRandomString } from "../../../common/helpers";

// In the test:
const userName = `FAS Test T${generateRandomString(5)}`;
const nickname = `FAST${generateRandomString(5)}`;
```

Because tests do **not** delete the records they create (see [Records and cleanup](#records-and-cleanup)), the data they leave behind must be identifiable. When creating records, give them **traceable names that tie back to the scenario** — combine a recognizable prefix (e.g. the chapter/feature or ticket) with the random suffix, so any entity on the environment can be traced to the test that created it. Prefer `` `OPTR-12345 webhook ${generateRandomString(5)}` `` over a bare random string. The random suffix keeps each run unique (so reruns never collide); the prefix makes the leftover data easy to find later.

Constants at the top of the file are for stable, shared values:

```ts
// Test data: OU names used across tests in this file
const OU_NAME = "Foundation AS - Bogus";
const SETTING_NAME = "Addresses:StateVisibleCountries";
```

#### Authentication

Use the one-liner `useAuthenticatedSession(test)` inside the `test.describe` block:

```ts
test.describe("Feature @regression @module-control-room @chapter-feature", () => {
  useAuthenticatedSession(test);
  // ...
});
```

Only use manual login (`LoginPage.login()`) when testing permission-specific behavior with different user accounts.

#### API calls in tests

Import `callEvaApi` directly and write API payloads inline in the test. This keeps the payload visible where it matters — as part of the test's intent:

```ts
import { callEvaApi } from "../../../common/helpers/api.helpers";

test("Employee can create a new API user", async ({ page, request }) => {
  const overviewPage = new ApiUsersOverviewPage(page);
  const detailPage = new ApiUsersDetailPage(page);
  const userName = `FAS Test T${generateRandomString(5)}`;
  const nickname = `FAST${generateRandomString(5)}`;

  // Navigate and create through UI
  await overviewPage.navigate();
  await overviewPage.btnCreate.click();
  await overviewPage.createApiUser(userName, nickname);

  // Assert the detail page
  await detailPage.assertOnDetailPage(userName);

  // Verify through API
  const userId = await detailPage.getUserIdFromUrl();
  const getResponse = await callEvaApi(request, "GetUser", { ID: userId });
  const userData = await getResponse.json();
  expect(userData.VisibilityGroup?.Name).toBe("Default");

  // No cleanup: the user is created with a unique, traceable name and left in place.
  // Do not delete it — only delete records when the delete itself is what the test verifies.
});
```

##### When the payload is always the same and parsing is complex

If the same API call with the same payload structure appears in many tests and the response parsing is non-trivial, it's okay to extract a utility helper (see the admin-suite-helpers skill). But for most cases, inline is better.

#### Test patterns

##### Create flow (UI action + API verification)

```ts
test("Employee can create a new entity", async ({ page, request }) => {
  const overviewPage = new OverviewPage(page);
  const detailPage = new DetailPage(page);

  await test.step("Navigate and open the create form", async () => {
    await overviewPage.navigate();
    await overviewPage.btnAdd.click();
  });

  await test.step("Fill in the form and submit", async () => {
    // ... fill form, submit ...
  });

  await test.step("Assert UI shows the created entity", async () => {
    await detailPage.assertOnDetailPage(ENTITY_NAME);
  });

  await test.step("Verify through API", async () => {
    const response = await callEvaApi(request, "GetEntity", { Key: ENTITY_NAME });
    const json = await response.json();
    expect(json.Value).toBe("expected-value");
  });
});
```

##### Update flow (API setup + UI action + API verification)

```ts
test("Employee can update an existing entity", async ({ page, request }) => {
  const detailPage = new DetailPage(page);

  await test.step("Setup: create the entity via API", async () => {
    await callEvaApi(request, "SetEntity", {
      Key: ENTITY_NAME,
      Value: "initial-value",
      OrganizationUnitID: 55,
    });
  });

  await test.step("Navigate to the detail page and edit", async () => {
    await detailPage.navigate(55, ENTITY_NAME);
    await detailPage.editValue("updated-value");
  });

  await test.step("Assert UI reflects the update", async () => {
    await detailPage.assertDetailShowsValue("updated-value");
  });

  await test.step("Verify through API", async () => {
    const response = await callEvaApi(request, "GetEntity", { Key: ENTITY_NAME });
    const json = await response.json();
    expect(json.Value).toBe("updated-value");
  });
});
```

##### Delete flow (API setup + UI action + API verification)

```ts
test("Employee can delete an existing entity", async ({ page, request }) => {
  const overviewPage = new OverviewPage(page);
  const detailPage = new DetailPage(page);

  await test.step("Setup: create the entity via API", async () => {
    await callEvaApi(request, "SetEntity", {
      Key: ENTITY_NAME,
      Value: "some-value",
      OrganizationUnitID: 55,
    });
  });

  await test.step("Navigate to detail and delete", async () => {
    await detailPage.navigate(55, ENTITY_NAME);
    await detailPage.deleteEntity();
  });

  await test.step("Assert redirect back to overview", async () => {
    await overviewPage.assertOnOverview();
  });
});
```

##### Validation flow (UI-only, no API)

```ts
test("Employee must manually select an Organization Unit", async ({ page }) => {
  const overviewPage = new OverviewPage(page);
  const createPage = new CreatePage(page);

  await test.step("Navigate and open the create form", async () => {
    await overviewPage.navigate();
    await overviewPage.btnAdd.click();
  });

  await test.step("Try to submit without required fields", async () => {
    await createPage.btnCreate.click();
    await createPage.assertStillOnCreatePage();
    await createPage.assertValidationErrorVisible();
  });
});
```

##### API request interception (for verifying payloads)

When a test needs to verify what the UI sends to the API:

```ts
test("Synchronization file is created with correct payload", async ({ page }) => {
  // Set up route interception before navigating
  const requestPromise = page.waitForRequest(
    (req) => req.url().includes("/CreateSynchronization") && req.method() === "POST"
  );

  // Navigate and trigger the action
  await syncPage.navigate();
  await syncPage.selectManager("Roles and rights");
  await syncPage.btnCreate.click();

  // Verify the intercepted request payload
  const request = await requestPromise;
  const payload = request.postDataJSON();
  expect(payload).toEqual({ Managers: [{ Name: "Roles" }] });

  // Verify the success modal
  await syncPage.assertDownloadModalVisible();
});
```

#### Records and cleanup

**Do not delete the records a test creates.** Tests must never remove their created entities as cleanup — no `DeleteX` call in an `afterEach`, and no "Cleanup" step that deletes test data. Instead, every record is created with a unique, [traceable name](#test-data) so reruns never collide and the leftover data stays attributable to the test that made it.

The **only** time a test deletes a record is when the deletion is the behavior under test — i.e. the test is specifically exercising a delete function. In that case the delete is the *action*, asserted like any other (see the [Delete flow](#delete-flow-api-setup--ui-action--api-verification) pattern), not teardown.

```ts
// Do NOT do this — deleting created data as cleanup is forbidden:
test.afterEach(async ({ request }) => {
  await callEvaApi(request, "DeleteUser", { ID: userId }); // ❌ no cleanup deletes
});
```

Reverting an EVA **setting** to its previous value is a different matter — that is restoring shared configuration state, not deleting a record, and is still expected (see [Setting-dependent tests](#setting-dependent-tests)).

##### Exception: entities that crowd a paginated overview grid

Traceable names keep leftover data *attributable*, but they do not keep it *harmless*. When a spec creates rows in a small, paginated overview grid, accumulation eventually pushes newly created rows past the first page and breaks assertions in unrelated tests.

Concretely: `tests/organizations/opening-hours/types.spec.ts` had no teardown, and the shared QA environment reached 31 opening hours types against a 25-row default page — enough that new rows landed on page 2 and intermittently failed other specs.

So for entities that appear as rows in a paginated overview grid, API teardown in `test.afterEach` **is** expected:

```ts
// Fine — the entity is a row in a paginated grid, so leaving it behind
// degrades the environment for every other spec that reads that grid.
test.afterEach(async ({ request }) => {
  await deleteOpeningHoursTypesByName(request, createdTypeNames);
  createdTypeNames.clear();
});
```

Rules for such cleanup:

- **Register the name, not just the ID**, so a test that fails before it learns the ID is still cleaned up.
- **Never fail the test from teardown** — the test result is authoritative.
- **Never swallow the error silently either.** Log it (`console.warn`), otherwise cleanup that has quietly stopped working looks identical to cleanup that works, and the accumulation returns unnoticed.
- **Respect delete ordering.** EVA rejects deletes that would orphan a reference — e.g. `DeleteOpeningHoursType` returns `OpeningHoursTypes:TypeHasTemplatesAndCannotBeDeleted` while any template still points at the type, so the template must be deleted first.

This exception does **not** extend to consumers, orders, employees, or other high-volume entities that are reached by search rather than by paging a grid; for those the original rule stands.

#### Test steps

Use `test.step()` to group related actions into named phases. This produces collapsible, named sections in the HTML report and trace viewer — making it immediately clear which phase of a test failed.

```ts
test("Employee can create a new entity", async ({ page, request }) => {
  const overviewPage = new OverviewPage(page);
  const detailPage = new DetailPage(page);

  await test.step("Navigate and open the create form", async () => {
    await overviewPage.navigate();
    await overviewPage.btnAdd.click();
  });

  await test.step("Fill in the form and submit", async () => {
    await createPage.fillForm(ENTITY_NAME);
    await createPage.btnCreate.click();
  });

  await test.step("Assert UI shows the created entity", async () => {
    await detailPage.assertOnDetailPage(ENTITY_NAME);
  });

  await test.step("Verify through API", async () => {
    const response = await callEvaApi(request, "GetEntity", { Key: ENTITY_NAME });
    const json = await response.json();
    expect(json.Value).toBe("expected-value");
  });
});
```

##### Step naming conventions

Use short, human-readable descriptions that describe **what** is being done:
- `"Setup: create the setting via API"` — for API-based test data setup
- `"Navigate to Settings and open the create form"` — for navigation
- `"Fill in the form and submit"` — for the main action
- `"Assert the detail page shows the correct values"` — for UI assertions
- `"Verify through API that the value was persisted"` — for API verification

##### Step descriptions must match assertions

The description of a `test.step` is a promise to the reader about what is being verified. The assertions inside the step must actually verify what the description claims. If a step says "Verify the error result is displayed", it must assert error-specific content — not just check that a Done button appeared.

```ts
// Bad: step says "error result" but only checks for Done button
await test.step("Verify the result dialog shows an error result", async () => {
  await detailPage.assertTestDialogResultButtons(); // only checks Done is visible
});

// Good: step says "error result" and actually verifies error content
await test.step("Verify the result dialog shows an error message and status code", async () => {
  await detailPage.assertTestDialogResultButtons();
  await expect(detailPage.textTestDialogStatusCode).toBeVisible();
  await expect(detailPage.headingTestDialogErrorMessage).toBeVisible();
});
```

Before writing a step, ask: "If I read only the step description, would I be surprised by what the assertions actually check?" If yes, either fix the assertions or fix the description.

##### When NOT to use test.step

- **`test.afterEach` teardown** (e.g. reverting a setting) — keep it flat, no steps needed
- **Single-action steps** — don't wrap a single line in a step (e.g., don't wrap just `await overviewPage.navigate()` in its own step)
- **Variable declarations** — page object constructors and test data go before the first step, not inside one

#### Setting-dependent tests

When a test needs to toggle an EVA setting (e.g. `Discounts:RequireVerification`) that affects frontend behavior, use the API-key-based setting helpers and the `.serial.spec.ts` naming convention:

```ts
import { test } from "@playwright/test";
import { useAuthenticatedSession } from "../../../common/useAuthStorage";
import { setSettingWithApiKey, unsetSettingWithApiKey } from "../../../common/helpers/evaSettingApi.helpers";

const SETTING_KEY = "Discounts:RequireVerification";
const SETTING_OU_ID = 1;

test.describe("Feature - Setting Dependent @regression @module-promotions @chapter-discounts", () => {
  test.describe.configure({ mode: "serial" });
  useAuthenticatedSession(test);

  test.beforeEach(async ({ request }) => {
    await setSettingWithApiKey(request, SETTING_KEY, "true", SETTING_OU_ID);
  });

  test.afterEach(async ({ request }) => {
    await unsetSettingWithApiKey(request, SETTING_KEY, SETTING_OU_ID);
  });

  test("Employee can perform action with setting enabled", async ({ page }) => {
    // ...
  });
});
```

Key points:
- The `.serial.spec.ts` suffix only serialises tests within the file; add the path to `ISOLATED_SPECS` in `playwright.config.ts` to also route it to the `chromium-serial` project (single worker, runs after regular tests)
- Use `test.describe.configure({ mode: "serial" })` for within-file ordering
- `setSettingWithApiKey` / `unsetSettingWithApiKey` authenticate via `API_USER_KEY` from `.env`, independent of the browser session
- For app settings, use `setAppSettingWithApiKey` / `unsetAppSettingWithApiKey` from the same helper file

Reference: `tests/promotions/discounts/discountsRequireVerification.serial.spec.ts`

#### What to avoid

- **Data builder functions** (`buildScenarioData()`) — use constants and inline values
- **Custom fixtures** (`test.extend<{...}>`) — use page object constructors in tests
- **Hardcoded entity IDs** — use names and look up IDs via API when needed
- **Raw selectors in specs** (`page.locator(...)`) — all selectors belong in page objects
- **Calling trivial page object wrapper methods** — for simple single-click actions, call the locator directly (e.g., `overviewPage.btnCreate.click()` not `overviewPage.startCreate()`)
- **Inline random generation logic** — use `generateRandomString()` from `common/helpers`
- **`waitForTimeout`** — wait on deterministic signals
- **Tests depending on execution order** — each test must be independently runnable
- **Assuming all entity types share the same form fields** — e.g., not all reason types have the same Name+Description pattern. Verify the actual fields per type before generating tests for multiple entity types. One wrong assumption can cascade into hundreds of failing tests.
- **Conditional workarounds for unexpected UI** — never add try/catch blocks to dismiss popups or conditional checks for dialogs that "might" appear. If the app shows unexpected UI (e.g., a language dialog, an error banner), that's a misconfiguration or environment issue. Fix it at the root cause (e.g., auth setup, test data) rather than adding fragile workarounds to every test. Workarounds mask real problems and should be flagged for investigation.

#### Verification — MANDATORY before delivering

**You MUST run the tests and confirm they pass before considering the work done.** Writing tests that look correct but fail at runtime wastes the user's time. This is not optional.

##### 1. Narrow run (debug loop)

Use while iterating on a failure:

```bash
npx playwright test <spec-file> --project=chromium --retries=0
```

An isolated green is **not** enough to deliver. Many Control Room / foundation flakes only appear under parallel workers.

##### 2. CI-parity suite run (required before delivering fixes)

Do **not** ship after only a single-spec run when the original failure was from CI or a multi-worker suite.

1. Find the workflow under `.github/workflows/` that covers the paths you changed (e.g. `foundation.yml` for `tests/control-room/` / `tests/organizations/`).
2. Copy the exact `npx playwright test ...` invocation from that YAML (paths, `--workers`, `--retries`, and any other flags).
3. Run that same command locally.

The workflow file is the **only** source of truth for how CI runs the suite — do not hardcode or invent flags in chat/skills. Treat Playwright `flaky` (failed then passed on retry) as unfinished — investigate and harden until the suite is clean, or report remaining flakes explicitly to the user.


##### Running from a git worktree

When the working directory is a git worktree (e.g. `.claude/worktrees/<name>`), the
gitignored files the test run needs are **not** present in the worktree — they only
exist in the main checkout. Copy them in from the main checkout instead of trying to
regenerate them:

```bash
# from inside the worktree, MAIN=<path to the main checkout>
cp "$MAIN/.env" .env
cp "$MAIN/playwright/.auth/user.json" playwright/.auth/user.json
```

Two specific gotchas this avoids:

- **`.env`** holds `BASE_URL`, `API_BASE_URL`, `APP_USERNAME`, `APP_PASSWORD`, etc.
  Without it, `dotenv` loads nothing, the `setup` project's `Login` call resolves to
  `undefined/message/Login`, and you get `SyntaxError: Unexpected token '<'` (an HTML
  404 page parsed as JSON). Copy `.env` first; do not re-author credentials.
- **`playwright/.auth/user.json`** is the stored session `useAuthenticatedSession`
  injects. It is gitignored, so a fresh worktree has none and the run fails with
  `Error reading storage state ... ENOENT`.

After copying `.env`, regenerate a fresh token with
`npx playwright test tests/auth.setup.ts --project=setup` (or run the chromium project
with its default `setup` dependency). The copied `user.json` only needs regenerating if
its token has expired (symptom: `401` on the first API call).

The git worktree itself is branched from `main` by default. If the code under test
lives on `develop` (or another branch), merge it in first (`git merge develop`) so the
page objects/helpers you depend on are present.

##### What to do when tests fail

1. **Read the error output carefully** — Playwright errors tell you exactly which locator failed and what it found instead
2. **Use `npx playwright cli` to inspect the actual UI** at the point of failure — don't guess what went wrong
3. **Fix the page object or test**, then re-run the **narrow** command
4. **Re-run CI-parity** for the affected suite — isolated passes alone are not acceptable
5. **Repeat until the CI-parity suite is green** (or remaining flakes are explicitly reported)

##### Common failure patterns to watch for

- **Strict mode violations** (`resolved to 2 elements`): Your locator matches multiple elements. Use `{ exact: true }`, scope to a container, or use `getByRole("heading", ...)` instead of `getByText(...)`
- **Element type mismatches**: A control might be a `button` in one state and a `link` in another (e.g., toggle controls). Use `clickFirstVisibleLocator` from `ui.helpers.ts` to handle both
- **Toast/notification text differences**: The actual toast message may differ from what the manual test document says. Always verify the exact text via `npx playwright cli` snapshot or screenshot
- **Timing issues after file uploads or API calls**: Wait for a deterministic signal (e.g., text appearing, dialog closing) rather than assuming the next action will work immediately
- **Dialog not closing**: After Save/Create/Delete, use `submitDialogAndWaitForMutation` from `ui.helpers.ts` (arm mutation response → submit → assert ok → dialog hidden). Do **not** sync mutations with `toBeHidden` alone. Probe the real `/message/<ServiceName>` — guessed names (`UpdateScheduledTask` vs `UpdateRecurringTask`) hang until timeout while the UI looks fine
- **Missed pressable row click**: Overview grids often have React Aria pressable rows with no `<a>`. Video/trace shows the overview still visible after "click". Use an `open*` PO method that requires detail URL (scroll + name cell + Enter retry). Assert navigation before detail alerts/values
- **Isolated pass, suite fail**: A test that passes alone can still flake under chapter/CI workers. Prefer wait/isolation fixes; **always** finish with the CI-parity command for that suite. Do not add `slowMo` or retry hacks in `useAuthStorage.ts`
- **Restricted / permission detail pages**: May hide normal detail chrome. Wait for the detail route (or the known permission alert), not always a full "General information" heading

##### Checklist before delivering

- [ ] Narrow debug run green: `npx playwright test <spec-file> --project=chromium --retries=0`
- [ ] **CI-parity suite green** — ran the exact `npx playwright test ...` line from the matching `.github/workflows/<suite>.yml`
- [ ] No unexplained `flaky` results left unreported
- [ ] No tests are skipped (unless explicitly agreed with the user)
- [ ] Test failures were debugged using actual UI inspection, not guesswork

#### Reference files

When writing new tests, read these existing specs to match the patterns:

- `tests/control-room/settings/general.spec.ts` — CRUD tests with API setup/verification
- `tests/control-room/appsettings/general.spec.ts` — menu-driven creation with app scoping
- `tests/control-room/settings/permissions.spec.ts` — manual login for different users
- `tests/control-room/settings/endpointConfigurationID.spec.ts` — dropdown-based editing
- `tests/control-room/settings/settingImpact.spec.ts` — multi-setting with impact dialogs

### Test account convention

Default to the user's own account for any test session needing a logged-in employee/user, unless the specific ticket requires a different account for a stated reason (a role/permission this account doesn't have, or a serial/multi-user scenario needing more than one distinct identity):

- **Account**: `andrei.luca@red-to-blue.com`
- **OU**: `lucatestaustriastore`

This account is **SSO-only** (confirmed: password login returns `FailureReason: 4`/InvalidCredentials). Use the `admin-suite-login` skill's SSO method to get an authenticated session for it -- that involves a pause where the user completes the actual login, since SSO can't be automated headlessly. For a fully automated, non-interactive run where nobody is available to complete that pause, fall back explicitly to this repo's standing automation account (`andrei.luca+10@red-to-blue.com`, local password in `.env`, see `admin-suite-login`) and say why.

If a scenario genuinely needs a different account or OU (e.g. testing a permission this account lacks, or OPTR-48129-style PIN/QR flows scoped to a specific dummy store), use this repo's existing per-ticket precedent for that need and say explicitly why the default account/OU wasn't used -- don't silently substitute a different account without a reason tied to the scenario.

### Standard file set

Every ticket run through this skill ends up with, under `tests/tickets/<ticket>/`:

- `<ticket>-context.md` -- via `personal_gather-context`
- `<ticket>-scenarios.md` -- via `personal_define-scenarios`
- `<ticket>-qa-checklist.md` -- this skill's own format, see Phase 1 step 4
- `<ticket>.spec.ts` (and `<ticket>.serial.spec.ts` if any scenario needs serial/multi-user execution) -- via `admin-suite-build-tests`, using `personal_test-specs`/`admin-suite-page-objects`/`admin-suite-helpers` for any missing building blocks
- `<ticket>-report.md` -- this skill's own format, see Phase 2 step 11 (standard for every ticket run through this skill, not optional)
- `<ticket>-testrail-cases.md` -- via `admin-suite-testrail-add-cases`

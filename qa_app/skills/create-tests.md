---
name: Create tests
description: Write the Playwright spec for the approved checklist.
---
# Create tests

You write a Playwright Test spec in TypeScript from the approved QA checklist. One checklist item is exactly one test, so results map back to the checklist.

## Structure
- Test titles start with the item number in brackets: `test('[3] Search ignores letter case', …)`.
- Keep the checklist order and section names (`test.describe` per section is fine).
- Read the base URL from the provided constant; never hard-code another environment.
- Prefix every piece of test data you create with the ticket key, so it can be found and cleaned up.

## Writing good tests
- Prefer user-facing locators: `getByRole`, `getByLabel`, `getByText`, `getByTestId`. Avoid CSS chains and XPath.
- Use web-first assertions (`await expect(locator).toBeVisible()`, `toHaveText`, `toHaveURL`), never fixed sleeps.
- **FE** items: drive the UI like a user and assert on what is shown.
- **BE** items: use the `request` fixture against the API; assert status, body shape and key fields, then read back to confirm persistence.
- **FE+BE** items: drive the UI and also check the network call or the API state behind it (`page.waitForResponse`).
- Arrange data through the API when possible; it is faster and more reliable than clicking through setup.

## Outcomes other than pass/fail
- Something only partly works: record `test.info().annotations.push({ type: 'qa-result', description: 'partial' })` with a short reason in the test.
- The test cannot run (missing data, missing permission, environment down): `description: 'blocked: <reason>'` and stop the test.

## Settings and cleanup
- Every setting you change must be reverted in `afterAll`, then read again to prove it was restored.
- Append each one as a JSON line `{name, value, reread}` to the file in `process.env.QA_CLEANUP_FILE`.
- Data that cannot be deleted (orders, payments, audit entries) stays, prefixed with the ticket key; note it in a comment.

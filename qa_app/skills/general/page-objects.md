---
name: Locators and page structure
parent: create-tests
---
# Locators and page structure

## Evidence before a locator

Never invent or extrapolate a locator. A locator needs evidence of what is really rendered: the pull request's markup or component code, a snapshot or screenshot the run produced, or the company's own page objects from onboarding. These do **not** count: another page in the same app, another entity type on the same page, the URL or the page name, or a "similar" existing page object. Headings, button types, dialog names and input roles vary from page to page.

A screenshot does not show which fields are required: required-field errors appear only after an empty submit, and often below the fold.

When the label in the code differs from the label you were told, use the real one and mention the mismatch in a comment.


## Locator order

Walk the element top-down and stop at the first yes:

1. A `data-testid`? `getByTestId("…")`
2. A role with an accessible name? `getByRole("button", { name: "Save" })`
3. A label or placeholder? `getByLabel("…")`, `getByPlaceholder("…")`
4. Unique visible text? `getByText("…")` or `.filter({ hasText: "…" })`
5. A stable structural selector (a heading level, an icon name, an attribute)? `locator("…")`
6. None of these: a short XPath, with a comment asking the developers for a `data-testid`.

Never use generated IDs (`:r0:`, `react-aria-123`) or CSS utility classes; they change between renders and releases.


## Scope

Scope child locators to their container so the same element elsewhere cannot match:

```ts
const dialog = page.getByRole("dialog", { name: "Edit setting value" });
await dialog.getByRole("textbox", { name: "Value" }).fill("42");
await dialog.getByRole("button", { name: "Save" }).click();
```

Never use a bare `getByRole("dialog")`: as soon as two dialogs are open it matches the wrong one.

Component libraries wrap most elements in extra containers, so sibling and ancestor XPath steps rarely work. Prefer scoping to a named container, or `nth()` counted from the markup.


## Find by identity, not by position (hard rule)

Anything that finds a record the test created, in a grid, a dropdown, an autocomplete, a picker or a list, searches or filters by that record's unique name first. Tests leave records behind, so the shared environment grows after every run: "the newest is first" holds once and then quietly stops holding.

```ts
// Do: narrow to the unique name, then act on that row.
await page.getByRole("searchbox", { name: "Name" }).pressSequentially(webhookName);
const row = page.getByRole("row").filter({ hasText: webhookName });
await expect(row).toBeVisible();
await row.getByRole("gridcell").first().click();
await expect(page).toHaveURL(/\/webhooks\/\d+/);
```

`.first()` is fine for one of several equivalent elements (the first cell of an already-filtered row). It is never a way to say "the one I just made".


## No speculative `.first()`, `.last()` or `.nth()`

Add one only when you have confirmed the locator matches more than one element. An unneeded `.first()` reads as evidence of an ambiguity nobody confirmed and misleads the next reader.


## Search and filter inputs

Some search and filter inputs react only to real keystrokes and silently ignore `.fill()`: no error, the grid keeps its old rows, and the test passes by luck until it does not. Use `.pressSequentially()` for any input that filters live results. `.fill()` is fine for ordinary form fields.


## Grids with clickable rows

Rows that open a detail page without a link can drop a click. Click a cell, then assert the detail URL before asserting detail content; retry once with focus and Enter if the URL did not change.


## Toasts and messages

Assert the exact message text, taken from the code or the ticket; it often differs from a manual test's wording. Find toasts in their notifications region, never with a generic "/success/i" match or a CSS class. When a toast follows a request, wait for the response first, then the toast.


## When the company has page objects

When onboarding shows the company's page objects, follow their shape in the spec: locators first, then multi-step actions named after what the user is trying to do (`editSettingValue`, not `clickPencilIcon`), then `assert…` methods. Do not wrap a single click in a method; call the locator directly.

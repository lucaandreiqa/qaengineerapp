---
name: UI updates and timing
parent: create-tests
---
# UI updates and timing

## Wait on signals, never on time

No `waitForTimeout`, fixed sleeps, `slowMo` or added retries. Wait for something that proves the app is ready: text appearing, a dialog closing, a URL changing, a response arriving. Web-first assertions (`await expect(locator).toBeVisible()`) already wait.

After a save, create or delete in a dialog: arm `page.waitForResponse` for the real service call before clicking, click, assert the response succeeded, then assert the dialog is hidden. Do not rely on `toBeHidden` alone, and take the service name from the code or the network, never from the button label; a wrong name hangs until the timeout while the UI looks fine.

After uploads and API calls, wait for a deterministic signal before the next action.


## Common failure patterns to avoid while writing

- **Strict mode** ("resolved to 2 elements"): use `{ exact: true }`, scope to a container, or use `getByRole("heading", …)` instead of `getByText(…)`.
- **A control changes type**: a button in one state can be a link in another; locate it by what stays the same.
- **"Page closed" mid-step**: usually the test timeout tore the page down while a wait hung on a wrong matcher. Fix the wait, do not raise the timeout first.
- **Restricted pages**: a page the user may only view can hide the normal layout. Wait for the route or the permission notice.
- **Passes alone, fails in a full run**: shared data or settings. Isolate data with unique names and keep setting changes in the serial spec.


## "The UI updates when …": find the mechanism first

A sentence like "switch tabs and see the other user" bundles different mechanisms, and each needs a different construct. Take the mechanism from the pull request; when it is not stated, say so in a comment.

- **Another tab changed storage** (localStorage or sessionStorage events): two pages in the **same** browser context; the change must happen live in one page after both have loaded. Seeding storage before load never fires the event. A new context inherits the project's saved session unless you pass `storageState: { cookies: [], origins: [] }`.
- **The window regains focus** (refetch on focus): `page.bringToFront()`.
- **Polling**: let the real interval pass, or control it; asserting immediately is a flaky test.
- **The same tab refreshes after its own save**: the default for create, update and delete; it does not reach other tabs.
- **Server push** (WebSocket, SignalR): needs a real server event. Without a way to trigger it, the scenario is not automatable; say so.

One test per mechanism, so a working one cannot hide a broken one.

`page.goto()` always reloads the whole app; a user's in-app click does not. A test about what happens "on navigation" needs the real click.

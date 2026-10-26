---
name: Test data, records and settings
parent: create-tests
---
# Test data, records and settings

## Test data

- Constants at the top of the file for stable values (organization unit names, setting keys).
- Data that must be unique per run gets a random suffix, and every record a test creates gets a traceable name tying it to the ticket: `` `PROJ-123 webhook ${suffix}` ``, not a bare random string. The suffix keeps reruns from colliding; the prefix makes leftover data easy to find.
- Do not hard-code entity IDs. Look them up through the API or use the human-readable name.
- Before relying on an account in a test, make sure it can sign in on this environment; accounts and their organization units differ per environment.


## Records: leave them, with traceable names

- **Tests do not delete the records they create.** No delete calls in `afterEach`, no cleanup step that deletes test data.
- A test deletes a record only when deletion is the behaviour under test. Then the delete is the action, asserted like any other.
- **Exception: rows in a small paginated overview grid.** Leftover rows push new ones past the first page and break other tests. For those, API teardown in `test.afterEach` is expected:
  - register the name, not only the ID, so a test that fails early is still cleaned up;
  - never fail the test from teardown;
  - log teardown errors with `console.warn` instead of swallowing them, or broken cleanup looks like working cleanup;
  - delete in the order references require (children before parents).
- This exception does not cover high-volume records reached by search (customers, orders, employees).
- Data that cannot be deleted at all (orders, payments, audit entries, minted codes) stays, prefixed with the ticket key. Say so in a comment.


## Settings: always revert

A setting is shared configuration, not a record, so it is always restored:

1. Before changing a setting, read and note its current value. That is what "original" means, not the documented default.
2. After the test, pass, fail or blocked, set it back to the noted value and read it again to prove it.
3. Append each one as a JSON line `{"name", "value", "reread"}` to the file in `process.env.QA_CLEANUP_FILE`.

Setting-dependent tests go in the serial spec, with `test.describe.configure({ mode: "serial" })`, the value set in `beforeEach` and reverted in `afterEach`.


## Shared environments

On a shared environment, do not create, change or delete shared or sensitive entities (company-wide configuration, other teams' data) unless the checklist explicitly calls for it. Never touch records the test did not create.

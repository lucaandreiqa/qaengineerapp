---
name: Gather requirements
description: Turn everything the ticket says into test scenarios and a QA checklist.
---
# Gather requirements

You read the whole Jira ticket (fields, description, acceptance criteria, every comment, linked tickets, attachment names) and turn it into scenarios and a QA checklist that a tester can execute against the test environment.

## Read the ticket like a tester
- Acceptance criteria are the contract. Every criterion becomes at least one checklist item.
- Comments can change the scope. When a later comment contradicts the description ("we dropped the CSV export", "max is now 50"), follow the latest agreement and say so in the scenarios.
- Linked tickets, labels and versions tell you the area and what else could break. Use them for regression items, not as new scope.
- Attachments (designs, screenshots, logs) are only known by name. Mention them when an item depends on them ("matches design.png").
- If something needed to test is missing or unclear (expected values, roles, limits), still write the item, and list the open question in the scenarios under "Open questions".

## By ticket type
- **FE** (frontend): what the user sees and does. Layout and states (loading, empty, error, disabled), validation messages, navigation, permissions in the UI, responsive behaviour if relevant, accessibility of new controls.
- **BE** (backend): the API contract. Status codes, response shape and fields, validation and error messages, permissions and auth, persistence (read it back), side effects, idempotency, limits and pagination.
- **FE+BE**: both, plus the integration: what the UI sends, what it shows for each backend outcome, and that data round-trips correctly.
- No FE/BE component or label: decide from the content and say which side each section covers.

## Writing checklist items
- One behaviour per item, phrased as a capability that is either true or false: "Search ignores letter case", not "Test search".
- Concrete values where the ticket gives them (limits, formats, texts).
- Cover the happy path first, then edge cases (empty, max, invalid, duplicate, special characters), then permissions, then regression of nearby behaviour.
- Group into 2–4 short sections named after the area ("Export", "Permissions", "Regression").
- Mark multi-user or concurrency scenarios (two sessions, race conditions, locking) so they run in a serial spec.
- Never invent results. Every item starts as NOT TESTED.

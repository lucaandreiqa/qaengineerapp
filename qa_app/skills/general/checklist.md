---
name: QA checklist
parent: gather
---
# QA checklist

Goal: the list of checks the tester approves at Gate 1 and the run fills in.


## Building it

1. Derive the items from the scenarios, and from the ticket's own "For QA" section when it has one; treat that section as the priority order.
2. Never add an item that does not trace back to the ticket, its pull request, its documentation or a scenario.
3. One behaviour per item, phrased as a statement that is true or false: "Search ignores letter case", "An employee without the edit permission sees the view-only notice".
4. Group items by feature or area. Number them globally across the whole checklist, not per group.
5. Mark multi-user and concurrency items so they run in the serial spec.
6. Every item starts as NOT TESTED. Nothing is a result until it has run.
7. Name anything intentionally out of scope, and why.


## Statuses, once the run has filled them in

- PASS: the run confirmed it.
- PARTIAL: partly confirmed; say what is and is not.
- FAIL: the run reproduced a defect.
- BLOCKED: another defect or the environment stopped it from running; say which.
- NOT TESTED: no coverage this pass, with the reason.

When a later run changes an item, the item shows the new status and evidence; the history lives in the run records, not as notes on every line.

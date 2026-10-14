---
name: Run tests
description: Judge the run, write clear bug notes, and rate severity.
---
# Run tests

The spec has run against the test environment. You look at each failed, partial or blocked checklist item with its error output and write what a developer needs to act on it.

## Is it a real bug?
- **Product bug**: the app does not do what the checklist item (and the ticket) says. Report it.
- **Test problem**: wrong selector, timing, test data assumption, or the test checked the wrong thing. Do not report it as a bug; say "Test needs fixing: …" so the spec is corrected.
- **Environment problem**: site down, 5xx on unrelated calls, login expired, missing seed data. Mark it blocked with the reason, not as a product bug.

## Bug note format
One or two sentences, no greeting:
1. What happens, with the exact input: `Searching " EXT-1042 " returns 0 orders.`
2. Why, when the error output shows it: `The UI sends the value untrimmed to SearchOrders.`
3. End with `Severity: Critical|Major|Minor`.

## Severity
- **Critical**: data loss or corruption, security or permission hole, payment wrong, the main flow of the ticket cannot be completed.
- **Major**: an acceptance criterion fails, wrong results, a workaround exists but is not obvious.
- **Minor**: cosmetic, wording, an edge case with an easy workaround, state not kept on reload.

Never change a result. Only explain it.

---
name: Update TestRail tests
description: Turn the passing checklist items into reusable TestRail cases.
---
# Update TestRail tests

You turn the checklist items that passed into TestRail test cases that someone can run again later, without reading the ticket.

## Each case
- **Title**: the behaviour, as in the checklist item, without the ticket key ("Search ignores letter case").
- **Steps**: numbered, concrete, starting from a known state ("1. Sign in as a user with the export permission. 2. Open Reports › Worked hours. 3. …"). Include the test data to use.
- **Expected**: what must be true at the end, observable by a tester.
- FE cases describe UI actions; BE cases describe the request (method, endpoint, key fields) and the expected response.

## Rules
- Only items that passed. Partial, failed and blocked items do not become cases.
- One case per behaviour. Merge items that test the same thing; do not repeat a case that already exists in the section (you will get their titles).
- Keep ticket-specific test data out of the title; put it in the steps.

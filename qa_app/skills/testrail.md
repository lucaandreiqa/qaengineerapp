---
name: Update TestRail tests
description: Turn the passing checklist items into reusable TestRail cases (YourQA's case guidance and the team's test-ticket phase 4).
---
# Update TestRail tests

You turn the checklist items that passed into TestRail cases someone can run again later without reading the ticket. This is a draft: YourQA shows it to the tester (Gate 4) and pushes nothing until they say so separately.

## Each case

- **Title**: the behaviour, as in the checklist item, without the ticket key ("Search ignores letter case").
- **Steps**: numbered, concrete, starting from a known state ("1. Sign in as a user with the export permission. 2. Open Reports > Worked hours. 3. …"). Include the test data to use.
- **Expected**: what must be true at the end, observable by a tester.
- Frontend cases describe UI actions; backend cases describe the request (method, endpoint, key fields) and the expected response.

## Rules

- Only items that passed. Partial, failed and blocked items do not become cases.
- One case per distinct concern. Merge items that test the same thing.
- Do not repeat a case that already exists in the section (you get their titles). Follow the section's existing style when there is one.
- Keep ticket-specific test data out of the title; put it in the steps.
- If TestRail reports an error when a case is added, the case may still have been created: YourQA verifies with the section's cases before ever retrying.

---
name: Update TestRail tests
---
# Update TestRail tests

You turn the checklist items that passed into TestRail cases someone can run again later without reading the ticket. This is a draft: YourQA shows it to the tester (Gate 4) and pushes nothing until they say so separately.

The skills under this one hold the detail: **Writing cases** and **Manual cases and automation**.


## The two phases

1. **Draft** (this step). Find the target section, check the section's existing case style, check for duplicates, and write the cases. All of it read-only against TestRail.
2. **Push**, only on the tester's separate, explicit go-ahead. YourQA re-reads the draft (the tester may have edited it), checks the section and duplicates again, creates one case per call, and verifies with the section's cases before ever retrying a call that returned an error, because TestRail can report an error and still create the case.

Approving the Jira comment never approves a push. A later edit to a case already in TestRail is a draft change too; it goes live only on its own explicit go-ahead.


## Rules

- Only items that passed become cases. Partial, failed and blocked items do not.
- One case per distinct concern. Merge items that test the same thing.
- Do not repeat a case the section already has; you get its titles. Flag close matches instead.
- When no section fits, propose a new one by name and parent. YourQA confirms it with the tester before creating it.

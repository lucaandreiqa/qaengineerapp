---
name: Comment & move Jira ticket
description: Write the QA result comment posted on the Jira ticket.
---
# Comment on the Jira ticket

You write the QA comment that is posted on the ticket after the results are approved. Developers and product owners read it; keep it short and factual.

## Shape
1. First line: `QA result: <passed>/<total> checks pass.` then where and when it was verified (environment, date, test account if one is set).
2. If anything failed: a **Bugs** section first, one bullet per failed item with its bug note and severity.
3. Then **Partial** and **Blocked** items with their reason, if any.
4. Then the passing checks grouped by section, one line each with ✅.
5. Cleanup: settings that were reverted, and test data left behind (with its prefix) when anything could not be deleted.
6. End with the signature line from settings.

## Rules
- Report only what the run found. No guesses, no "probably works".
- Use the checklist wording so it can be matched to TestRail later.
- Markdown with **bold** section titles and bullets; no tables, no headings larger than bold.
- Do not recommend the next status; moving the ticket is a separate approval.

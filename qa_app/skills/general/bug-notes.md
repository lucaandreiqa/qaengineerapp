---
name: Bug notes and severity
parent: run-tests
---
# Bug notes and severity

## The note

Start short, then give what a developer needs:

1. What happens, with the exact input: `Searching " EXT-1042 " returns 0 orders.`
2. Why, when the error output or the pull request shows it: `The UI sends the value untrimmed to SearchOrders.`
3. For a product defect: the setup, the exact steps or requests, the raw result (status codes, error messages, the state before and after), your analysis, and a recommendation.
4. End with `Severity: Critical|Major|Minor`.

Write the note for the product owner and the developer: plain product language about what happens, no tool or test-framework names.


## Severity

- **Critical**: data loss or corruption, a security or permission hole, money wrong, or the ticket's main flow cannot be completed.
- **Major**: an acceptance criterion fails, wrong results, or the workaround is not obvious.
- **Minor**: cosmetic, wording, an edge case with an easy workaround, state not kept on reload.


## Remarks from the run

Something the run noticed that is not a failing check (an inconsistency, an accessibility problem, a misleading name, a permission path that was not automated) becomes a remark, numbered after the existing ones:

```
### R<N> - <short title>
- Steps to reproduce:
  1. <step>
- What is wrong: <one or two sentences>
- Evidence: <screenshot or trace from the run, when there is one>
```

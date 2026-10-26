---
name: Run tests
---
# Run tests

The spec has run against the test environment. For each failed, partial or blocked checklist item you get its error output, and when GitHub is connected, what the pull request changed. You decide what each failure is and write what a developer needs to act on it. The tester reviews it at Gate 2; nothing reaches Jira before that.

The skills under this one hold the detail: **Why a check failed** and **Bug notes and severity**.


## Results are facts

- Never change a result. A status other than NOT TESTED or BLOCKED comes from something that ran; you explain it, you do not re-judge it.
- Never present a guess as a finding. When the evidence does not point clearly to one cause, say so.


## Cleanup is part of the run

- Every setting changed during the run is reverted to the value it had before, and the revert is verified by reading it again, whatever the outcome. Record what was changed, what it went back to, and that the re-read confirmed it.
- Test data that could not be deleted stays, prefixed with the ticket key. Say what was left behind.


## The report

- A summary: how many checks passed and failed, the defects found, anything blocked.
- What was tested, mirroring the checklist.
- **Caught during testing**: a check that failed, was fixed by the developer, and now passes. This is not a remark; it records that the testing caught something real before delivery. Keep these lines when later runs pass.
- Remarks still open, with their R numbers.

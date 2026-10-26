---
name: Manual cases and automation
parent: testrail
---
# Manual cases and automation

Manual cases are written for efficiency: one walk through a feature, checking everything on the way. Automated tests are written for isolation: one behaviour each, so a failure says exactly what broke. Moving between the two follows these rules.


## A manual case becomes several tests

- **One test, one concern.** A case that creates, edits, adds a permission and deletes becomes at least one test per behaviour: "Employees can create an API user", "Employees can add a permission to an API user", and so on.
- A validation step in the middle ("press Create without a name, verify the error") becomes its own test.
- "If X then Y, else Z" becomes one test per branch.
- A closing "delete what you created" step is the tester tidying up, not a behaviour: the automated tests leave their records under traceable names. Only a delete that the case actually verifies becomes a test, with the delete as the action.


## What to automate

- Always: create, read, update and delete; form validation; permissions; navigation and the page a user ends up on; impact and confirmation dialogs.
- Consider skipping, with the reason written down: email delivery, purely visual checks, steps that wait minutes for something, steps in external systems.
- Partial coverage is fine. Record which steps are covered and why each uncovered one is not. Mark a case as automated only when every step is covered.


## A test plan from a case

For each test: its capability-statement name, the setup (through the API when possible), the steps, the assertions, and the record it leaves behind. Then list the steps not automated with their reason, the steps dropped as tidy-up, and the gaps (page helpers or locators still needed).


## Names

Test and case names read as capability statements that say what broke when they fail. "Employees can manage API users" is too broad; "API user CRUD" says nothing.

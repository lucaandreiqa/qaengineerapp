---
name: Scenarios
parent: gather
---
# Scenarios

Goal: every behaviour the change touches, written as scenarios a tester or a test can verify by looking at the screen, grouped by topic.


## 1. The state and action matrix (mandatory, before any scenario)

For each affected component or section:

1. List every state it can be in. Keep the states that existed before the change: if the change adds "deleted endpoint", the "has endpoint" and "never had an endpoint" states stay in.
2. List every action a user can take in each state.
3. Every valid state and action pair gets a scenario. Present the matrix as a table with the columns State, Action and Scenario, so the coverage can be checked.
4. A state that cannot be set up through the API or the UI (an entity without a required field, a third-party sign-in redirect, a clock-dependent trigger) goes under **Not automatable**, with the reason. A person may still test it by hand.


## 2. Writing the scenarios

- **One scenario, one behaviour.** Break combined flows apart: create, read, update and delete are separate scenarios; required-field and format validation are separate; one scenario per role for permissions; one per setting state for setting-dependent behaviour.
- **Every variation that behaves differently.** When behaviour differs per entity type, write scenarios for every in-scope type. When all types behave the same, one parameterised scenario is enough.
- **Everything the ticket asks for**, comments included. When the ticket or its context has a checklist, every item gets at least one scenario. Acceptance criteria get their own topic.
- **What the user sees**, not what the API returns. Outcomes are concrete and observable: "the detail page shows the monitor name", not "the monitor is created successfully". Say where navigation ends up and what a dialog shows.
- **One scenario per mechanism.** When "the UI updates" could be caused by different mechanisms (a change in another tab, the window regaining focus, polling, a server push, the same tab refreshing after a save), write one scenario per mechanism the change involves, so a working one cannot hide a broken one.
- **Find by identity.** A scenario about a record the test created names that record ("the row named PROJ-123 webhook …"), never its position ("the first row").
- Cover every test type that applies: happy path, validation, error handling (a failed save, a slow response, a loading state), permission, setting-dependent, edge cases (empty state, large data, special characters), data verification (after an action, check all visible data, not one field), adjacent flows (other operations still work while the entity is in an unusual state), and regression of nearby behaviour.
- When the expected outcome is unknown, do not assume it: write the scenario and add the question to "Open questions".


## Format

Statement style, for one flow: a single sentence that is true or false.

```
After creating an endpoint configuration named "Test EC", the detail page shows that name and the endpoint URL.
```

Table style, for the same flow across types or settings:

```
| Reason type      | Can create | Can edit name | Requires organization unit |
|------------------|------------|---------------|----------------------------|
| Open cash drawer | yes        | yes           | no                         |
| Tax exemption    | yes        | yes           | yes                        |
```

The scenarios end with these sections, in this order: **Not automatable** (each item with its reason), **Open questions**, **Data impact** (what a run would create, update and delete; any shared or sensitive entity involved; confirmation that every created record gets a unique, traceable name and no existing data is touched), and **Remarks**.


## Remarks

A finding that is not asserted as a scenario, a disagreement between the ticket and the code or the docs, or anything the product owner or developer should know, becomes a remark:

```
### R<N> - <short title>
- Steps to reproduce:
  1. <step>
  2. <step>
- What is wrong: <one or two sentences, a neutral observation>
- Evidence: <file references, when there are any>
```

Number remarks in order. The same number follows the remark into the results and the QA notes.


## Do not

- Add priority or type metadata to scenarios.
- Use vague outcomes ("works correctly", "behaves as expected").
- Merge distinct behaviours, or drop an item a checklist asked for.

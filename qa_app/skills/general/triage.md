---
name: Why a check failed
parent: run-tests
---
# Why a check failed

Classify every failure on evidence before anyone touches an assertion or a locator. "Make it pass" is right for only some causes; applied to the others it either ships a real defect as expected behaviour or bakes a wrong assumption in deeper.


## The causes

| Cause | What it means | What counts as evidence |
|---|---|---|
| Product defect | The app does not do what the item and the ticket say | The error output contradicts the ticket or its accepted behaviour, especially in code the pull request touched |
| Regression | Behaviour outside the change broke | Something that used to hold, unrelated to the ticket's scope, now fails, and nothing in the ticket explains it |
| Flaky or timing | The test is not deterministic; the feature is fine | The output shows a race (the element or response arrived after the assertion), or the same check passed and failed across runs |
| Stale locator | The UI changed shape but still works | The locator expected an element the current markup or snapshot does not have, while the feature is visibly there |
| Wrong assumption | The test asserted something that was never reliably true, or stopped being true as the environment changed ("the new row is on the first page") | The item or the test assumed it, not the ticket |
| Environment | Site down, server errors on unrelated calls, sign-in expired, a consent or bot-check page, missing seed data | The failure is outside the app's behaviour |

These do **not** count as evidence: the error message alone, "probably a UI change" without looking at the markup, one rerun that passed as proof of flakiness, or whichever cause needs the least work.


## What each cause becomes

- **Product defect or regression**: a bug note (see Bug notes and severity). Never "fix" the test to match broken behaviour. If the change is intentional and documented on the ticket, say so and cite it instead.
- **Flaky or timing**: "Test needs fixing", naming the deterministic signal to wait for. Never a sleep, retries or `slowMo`.
- **Stale locator**: "Test needs fixing", naming the element as it is now rendered.
- **Wrong assumption**: "Test needs fixing", saying what is actually true. For a position-based lookup, find the record by its unique name.
- **Environment**: BLOCKED with the reason, not a product bug.

Use the pull request to tell them apart: a failure in a file the pull request touched points to the change; a failure far from it often points to the test or the environment.


## Siblings

When one cause is a shared locator, helper, setting or account, other checks that depend on it probably failed for the same reason. Group them under one explanation instead of repeating it.

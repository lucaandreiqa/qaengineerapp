---
name: Ticket context
parent: gather
---
# Ticket context

Goal: understand what changed, which pages and flows it touches, which services, settings and permissions are involved, where it can be tested, and what test coverage already exists.


## Approach

1. **Name the core change.** A new feature, a bug fix, a redesign, a new setting, a new API property shown in the UI, a backend-only change.
2. **Read the pull request before the ticket's reproduction notes.** Its commits name the real components, routes, API services, field names and enum values. Note deliberate exceptions, regressions fixed in passing and the root cause of any follow-up fix commit, and carry them into the scenarios. Commit messages are not review comments; do not present one as the other.
3. **Affected pages and flows.** Name each by its navigation path in the app ("Settings > Users > Detail page"). Do not assume a page is affected without evidence in the ticket, the pull request or the docs.
4. **API and settings surface.** For each service or endpoint the affected pages call, the properties that matter for this change. For each setting or feature flag, whether it changes what is visible, how a form behaves, or who can open the page.
5. **Impact dimensions.** For every affected area, check which apply:
   - UI states: empty, loading, loaded, error, permission denied.
   - Setting-dependent behaviour: does the UI change with a setting value?
   - Permission-dependent behaviour: do roles see or do different things?
   - Entity-type variations: does the same screen behave differently per type? Never assume two types share a form.
   - Form validation: required fields, enforced formats, business rules.
   - Confirmation and impact dialogs.
   - Anything else the ticket or its comments ask for, including "would be nice" improvements in comments.
6. **Existing coverage.** From the TestRail cases you were given and the pull request's own tests: what is already covered for this area, and where the gaps are.
7. **Where to test.** The environment decides everything downstream, so resolve it explicitly:
   - Classify the ticket (frontend, backend or both) from its components and labels. A backend-only ticket is tested through the API unless a UI for the area is confirmed.
   - An unmerged change is tested on its own preview or pull-request environment, taken from the ticket or its comments. A merged change is tested on the shared test environment.
   - When the environment YourQA gives you does not match what the ticket says, or the ticket names no API endpoint and one is needed, say so under "Open questions". Do not build anything against an assumed environment.


## Output: the analysis

Prose and tables, no bullet points or emojis:

- **About**: a short summary, the ticket description as written, the comments summarised with the outcome of each discussion, and acceptance criteria only when the ticket explicitly has them.
- **Affected pages**, by navigation path.
- **Services and settings**, with the properties and effects named above.
- **Existing coverage**: what exists and the gaps.
- **Deployment**: the ticket type, the environment to test on, the API endpoint.
- **Open questions**: everything you could not check, everything unclear, every disagreement between sources.


## Do not

- Invent or infer acceptance criteria.
- Present a source as checked when it was not given to you.
- Guess a URL from another one; say which one is missing.

---
name: Writing cases
parent: testrail
---
# Writing cases

## Each case

- **Title**: the behaviour, as a capability statement, without the ticket key: "Employees can manage tax rates", "Search ignores letter case".
- **Preconditions**: only setup that must exist before the steps start: the permissions or settings the user needs and how to get them, required test data and where it comes from, or a dependency on another case. Plain navigation belongs in the steps. Leave preconditions empty when a signed-in user is all it needs.
- **Steps**: numbered, short imperative actions from a known state ("Open Financials > Tax management.", "Click Add.", "Fill in Country = Burundi, Tax code = ReturnCost, VAT = 20%."). Include the test data in the steps, not the title.
- **Expected results**: one per step, in the same order, describing what a tester observes ("The Tax management page is shown.", "The tax rate appears in the list.").
- Frontend cases describe UI actions; backend cases describe the request (method, endpoint, key fields) and the expected response.

## Match the section

Follow the style of the existing cases in the target section: the same template, the same fields (one rich-text steps field, or separate step and expected pairs), the same type and priority conventions. Check an existing case rather than assuming. Use the default priority unless a case is clearly more or less important, and say why when you deviate.

When the section's cases link automated tests in their references field, add the spec path the same way.

## Write them for people

Plain product language a tester can follow cold. No tool names, no internal file paths.

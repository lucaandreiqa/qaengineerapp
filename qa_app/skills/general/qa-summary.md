---
name: QA summary comment
parent: jira-comment
---
# QA summary comment

Use this template:

```
QA result: <X>/<Y> checks pass. Verified <date> against <environment> (<account and organization unit>). All test data created this pass is isolated and traceable, prefixed <ticket>.

**<Section 1 name, as in the checklist, without its number>**
✅ <capability statement: what works, not "item 3 passed">
✅ <capability statement>

**<Section 2 name>**
❌ <capability statement>. Severity: Major

**Caught during testing**
✅ <capability statement>: failed at first (<short cause>), fixed by the developer, passes now

<signature line>
```

## Rules

- One line per checklist item, a capability statement condensed from that item's evidence, not copied verbatim. Use the checklist wording closely enough that the comment can be matched to TestRail later.
- The status marker goes at the **start** of each line: ✅ pass, ⚠️ partial, ❌ fail, 🚫 blocked, ⬜ not tested.
- Section names are **bold**, not headings.
- The first line always gives the pass count, the date, the environment and the account context, plus the line about traceable test data whenever the run created any.
- When not everything passed, keep the same structure: put the items that did not pass under their own bold section (for example **Not covered this pass**) with their markers, and give the severity of every failure.
- Include **Caught during testing** only when there are such lines.
- Mention settings that were changed and reverted, and test data left behind with its prefix.
- End with the signature line from YourQA's settings, on its own line.

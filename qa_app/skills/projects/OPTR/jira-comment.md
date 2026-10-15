---
name: Comment & move Jira ticket (OPTR)
mode: add
---
# For OPTR (EVA Suite Admin)

EVA Suite Admin specifics for OPTR tickets, taken word for word from the team's original skills. They add to the general skill above; where they are more specific, follow them. Where they ask you to fetch something yourself (Jira, gh, git, TestRail), use what YourQA already fetched in `<connected_apps>` instead, and list what is missing under Open questions.

### Phase 3 -- Report and transition on Jira

These are visible, shared, external actions. Follow the exact confirmation bar `admin-suite-jira-comment` already requires -- show the user the content before sending, every time, even though this is one continuous workflow. This phase contains mandatory review gate #3, split into its two independent halves below.

14. **Post a QA summary comment**, using this exact template (established 2026-08-28 on OPTR-48370/OPTR-48364 - supersedes any earlier plain-text-only guidance; the Atlassian comment tool's `contentFormat: "markdown"` renders bold headers and leading checkmarks correctly, so this is the standard format for every QA summary comment posted via this skill going forward):

    ```
    QA result: <X>/<Y> checks pass. Verified <date> against <environment> (<account/OU context, e.g. "SSO account, OU 7 'NBQA Dummy' plus freshly-created OUs/devices under it">). All test data created this pass is isolated and traceable, prefixed <ticket>.

    **<Section 1 name, matching the checklist's own `## <N>. <Section>` grouping, number dropped>**
    ✅ <capability statement - what works, not "item 3 passed">
    ✅ <capability statement>

    **<Section 2 name>**
    ✅ <capability statement>
    ...

    Commented by Claude for Luca
    ```

    Rules for this template:
    - One line per checklist item, phrased as a capability statement derived from that item's own evidence sentence - condensed, not copy-pasted verbatim.
    - The status marker (✅/❌/🚫/⬜, matching the checklist's own legend) goes at the **start** of each line, never the end.
    - Section names are **bold** (`**Section Name**`), not `#` headers - this renders correctly via the tool's markdown support and matches the two established examples.
    - The intro line always states the X/Y pass count, verification date, target environment, and account/OU context, plus a line noting created test data is isolated/traceable (prefixed with the ticket key) whenever any test data was created.
    - If the pass isn't 100% green, still use the same bold-section/leading-marker structure - group non-passing items under their own section (e.g. `**Not covered this pass**`) using the matching ❌/🚫/⬜ marker at the start of each line, same as a PASS line. Call out severity for any ❌ FAIL per the existing rule below.
    - Build the actual content from the checklist/report (a concise summary, not a raw file dump) - this template governs formatting, not which items to include.
    - End with the attribution line `Commented by Claude for Luca` on its own line, per `admin-suite-jira-comment`.
    - Show the exact text and get explicit confirmation before posting.
15. **Transition the ticket's status**, only if a target state was given (as an input, or by asking now if it wasn't given upfront):
    - Call `getTransitionsForJiraIssue` for this ticket and match the target state by exact name (case-insensitive) against the returned transition names -- do not guess or fuzzy-match to a similarly-named state.
    - If no matching transition exists from the ticket's current status, stop and tell the user which transitions actually are available -- do not force it via a different mechanism (e.g. editing the status field directly).
    - Show the user the current status -> target status and get explicit confirmation before calling `transitionJiraIssue`.
    - This is a separate write from the comment above -- confirming the comment does not implicitly confirm the transition, and vice versa.

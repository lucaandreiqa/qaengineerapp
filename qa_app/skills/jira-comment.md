---
name: Comment & move Jira ticket
description: Write the QA result comment and move the ticket (the team's test-ticket phase 3 and unslop skills).
---
# Comment & move Jira ticket

## End-to-end workflow, phase 3 (personal_test-ticket)

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

## Writing: unslop

### Unslop

Edit text to remove AI patterns.

#### Process

 1.⁠ ⁠Scan for the patterns below.
 2.⁠ ⁠Rewrite. Preserve meaning, match intended tone.
 3.⁠ ⁠Self-audit: "What makes this obviously AI generated?" Fix remaining tells.

#### Patterns to detect and fix

Rule numbers are stable ids that other skills cite. A removed rule leaves a gap.

##### Content

 3.⁠ ⁠*Superficial -ing phrases.* "highlighting...", "ensuring...", "reflecting...", "showcasing...", "fostering...". Delete or expand with real sources.
 4.⁠ ⁠*Vague attributions.* "Experts believe", "Industry reports suggest", "Some critics argue". Name the source or delete.

##### Language

 7.⁠ ⁠*AI vocabulary.* Additionally, crucial, delve, enduring, enhance, fostering, garner, interplay, intricate, landscape (abstract), pivotal, showcase, tapestry (abstract), testament, underscore, vibrant. Replace with plain words.
 8.⁠ ⁠*Fancy ways to say "is".* "serves as", "stands as", "boasts", "features". Just say "is" or "has".
 9.⁠ ⁠*"Not just X, but Y."* State the point directly instead.
10.⁠ ⁠*Rule of three.* Forcing ideas into groups of three. Use the natural number.
11.⁠ ⁠*Synonym cycling.* Protagonist, main character, central figure, hero all in one paragraph. Pick one, repeat it.
12.⁠ ⁠*False ranges.* "from X to Y" where X and Y aren't on a meaningful scale. List topics directly.

##### Style

13.⁠ ⁠*Em dash overuse.* Avoid em dashes entirely. Use periods or commas only (no parentheses, no en dashes, no hyphen-as-dash substitutes). If a thought needs separation, end the sentence or use a comma.
14.⁠ ⁠*Colon overuse.* Colons are fine before a list or example. Not as mid-sentence connectors. "If you're coming from traditional automation: instead of registering event handlers, you describe conditions" adds nothing with the colon. Rewrite to let the point stand on its own without comparison framing. "Describing when the scheduler should fire works best as plain English." Same meaning, no crutch punctuation.
15.⁠ ⁠*Boldface overuse.* Don't bold every proper noun or acronym.
16.⁠ ⁠*Inline-header lists.* The tell is a bold label and colon that restates the line: "*Performance:* Performance improved...". Convert those to prose. A bold lead-in that ends in a period, names the item, and is followed by genuinely new detail ("*Schema in TypeScript.* Tables live in one file.") is fine, not a tell.
17.⁠ ⁠*Title case headings.* Use sentence case.
18.⁠ ⁠*Decorative emojis.* Remove from headings and bullets.
19.⁠ ⁠*Curly quotes.* Replace with straight quotes.

##### Communication artifacts

20.⁠ ⁠*Chatbot phrases.* "I hope this helps!", "Let me know if...", "Of course!", "Certainly!", "Found the smoking gun!" Remove.
21.⁠ ⁠*Sycophantic tone.* "Great question! You're absolutely right!" Respond directly.

##### Filler

23.⁠ ⁠*Filler phrases.* "In order to" becomes "To". "Due to the fact that" becomes "Because". "It is important to note that" gets deleted.
24.⁠ ⁠*Excessive hedging.* "could potentially possibly be argued that it might" becomes "may".
25.⁠ ⁠*Generic conclusions.* "The future looks bright." State specific plans or facts.

##### Jargon

26.⁠ ⁠*Abstract metaphor nouns.* Substrate, wedge, vector, locus, vantage, nexus, primitive (as noun), harness (as metaphor), surface (as in "API surface"), bedrock, scaffolding (as metaphor), modality, paradigm, gold-plating, ratchet (as metaphor), evacuate (for moving code), endgame, north star, flywheel. These read as technical but usually have a plainer concrete word. "Substrate" becomes "base". "Wedge in" becomes "add". "Vector" becomes "way" or "method". "Gold-plating" becomes "more than the job needs". "Ratchet" becomes the mechanism's real name or "a limit that only tightens". "Evacuate" becomes "move out". "Endgame" becomes "the last phase". Pick the concrete word.

##### Plain speech

27.⁠ ⁠*Say what it does, not how it feels.* "the database stays close at hand", "SQL you can read", "types that follow your schema" name a feeling. The fix names the mechanism or a number: "⁠ .toSQL() ⁠ returns the exact string sent to the database", "a column rename fails the build". Ask what the sentence tells the reader to do or know, then write that. If you can't restate it as a concrete instruction, fact, or number, cut it. One more check: if the sentence could appear unchanged in another project's docs, it says nothing about this one. Cut it.
28.⁠ ⁠*Shorten or split dense sentences.* If the reader has to backtrack to parse a sentence, break it in two or drop clauses. One idea per sentence.
29.⁠ ⁠*Active voice.* Prefer it. Catch "is/are/was/were + past participle" and name the actor: "queries are validated" becomes "the compiler validates queries", "the file is parsed by the loader" becomes "the loader parses the file". Passive is fine only when the actor is unknown or genuinely doesn't matter.
30.⁠ ⁠*Cut adverbs, or use a stronger verb.* "runs quickly" becomes "is fast" or the number. "significantly improves" becomes the measured delta. An adverb propping up a weak verb means the verb is wrong.
31.⁠ ⁠*Prefer the plain word.* "utilize" becomes "use", "leverage" becomes "use", "facilitate" becomes "help", "numerous" becomes "many", "in the event that" becomes "if". The fancier synonym is rarely clearer.
32.⁠ ⁠*Mannered prose.* Metaphor or flourish where a literal phrase exists: aphorisms ("wire it or delete it"), rhetorical fragments for effect, personified code ("the plan holds it"), figurative verbs ("rides along", "stands on"), stock framing phrases. "A dial worth turning" becomes "a parameter worth varying". Say what you mean. Rule 26 covers the metaphor nouns.
33.⁠ ⁠*Over-compression.* Dropped articles, verbless fragments, symbol-speak, and abbreviations that make the reader decode instead of read. "Parser rejects bad date → exit 2, no write" becomes "The parser rejects a bad date, exits with code 2, and writes nothing." Write whole sentences with their articles and verbs, and spell out arrows and abbreviations.

---
name: Comment & move Jira ticket
description: Write the QA result comment and move the ticket (the team's test-ticket phase 3 and unslop).
---
# Comment & move Jira ticket

These are visible, shared actions. YourQA shows the tester the exact comment before it is posted and asks again before the ticket moves; approving one never approves the other.

## The QA summary comment

Use this template:

```
QA result: <X>/<Y> checks pass. Verified <date> against <environment> (<account/OU context>). All test data created this pass is isolated and traceable, prefixed <ticket>.

**<Section 1 name, as in the checklist, without its number>**
✅ <capability statement: what works, not "item 3 passed">
✅ <capability statement>

**<Section 2 name>**
❌ <capability statement>. Severity: Major

<signature line>
```

Rules:

- One line per checklist item, phrased as a capability statement condensed from that item's evidence, not copied verbatim.
- The status marker goes at the **start** of each line, never the end: ✅ pass, ⚠️ partial, ❌ fail, 🚫 blocked, ⬜ not tested.
- Section names are **bold**, not headings.
- The intro line always states the pass count, the verification date, the environment and the account context, plus the line about traceable test data whenever any test data was created.
- When not everything passed, keep the same structure: group the items that did not pass under their own bold section (for example **Not covered this pass**) with the matching marker at the start of each line, and give the severity of every failure.
- Build the content from the checklist and the report: a concise summary, not a raw dump.
- Report only what the run found. No guesses, no "probably works".
- Use the checklist wording so the comment can be matched to TestRail later.
- Mention reverted settings, and any test data left behind with its prefix.
- End with the signature line from YourQA's settings, on its own line.
- Do not recommend the next status in the comment.

## Moving the ticket

- The target state is matched by its exact name against the transitions Jira returns for the ticket. Never guess or fuzzy-match a similar name.
- If the target state is not available from the current status, YourQA shows the tester which transitions are; never force the move another way.

## Writing: unslop

### Unslop

Edit text to remove AI patterns.

#### Process

 1. Scan for the patterns below.
 2. Rewrite. Preserve meaning, match intended tone.
 3. Self-audit: "What makes this obviously AI generated?" Fix remaining tells.

#### Patterns to detect and fix

Rule numbers are stable ids that other skills cite. A removed rule leaves a gap.

##### Content

 3. *Superficial -ing phrases.* "highlighting...", "ensuring...", "reflecting...", "showcasing...", "fostering...". Delete or expand with real sources.
 4. *Vague attributions.* "Experts believe", "Industry reports suggest", "Some critics argue". Name the source or delete.

##### Language

 7. *AI vocabulary.* Additionally, crucial, delve, enduring, enhance, fostering, garner, interplay, intricate, landscape (abstract), pivotal, showcase, tapestry (abstract), testament, underscore, vibrant. Replace with plain words.
 8. *Fancy ways to say "is".* "serves as", "stands as", "boasts", "features". Just say "is" or "has".
 9. *"Not just X, but Y."* State the point directly instead.
10. *Rule of three.* Forcing ideas into groups of three. Use the natural number.
11. *Synonym cycling.* Protagonist, main character, central figure, hero all in one paragraph. Pick one, repeat it.
12. *False ranges.* "from X to Y" where X and Y aren't on a meaningful scale. List topics directly.

##### Style

13. *Em dash overuse.* Avoid em dashes entirely. Use periods or commas only (no parentheses, no en dashes, no hyphen-as-dash substitutes). If a thought needs separation, end the sentence or use a comma.
14. *Colon overuse.* Colons are fine before a list or example. Not as mid-sentence connectors. "If you're coming from traditional automation: instead of registering event handlers, you describe conditions" adds nothing with the colon. Rewrite to let the point stand on its own without comparison framing. "Describing when the scheduler should fire works best as plain English." Same meaning, no crutch punctuation.
15. *Boldface overuse.* Don't bold every proper noun or acronym.
16. *Inline-header lists.* The tell is a bold label and colon that restates the line: "*Performance:* Performance improved...". Convert those to prose. A bold lead-in that ends in a period, names the item, and is followed by genuinely new detail ("*Schema in TypeScript.* Tables live in one file.") is fine, not a tell.
17. *Title case headings.* Use sentence case.
18. *Decorative emojis.* Remove from headings and bullets.
19. *Curly quotes.* Replace with straight quotes.

##### Communication artifacts

20. *Chatbot phrases.* "I hope this helps!", "Let me know if...", "Of course!", "Certainly!", "Found the smoking gun!" Remove.
21. *Sycophantic tone.* "Great question! You're absolutely right!" Respond directly.

##### Filler

23. *Filler phrases.* "In order to" becomes "To". "Due to the fact that" becomes "Because". "It is important to note that" gets deleted.
24. *Excessive hedging.* "could potentially possibly be argued that it might" becomes "may".
25. *Generic conclusions.* "The future looks bright." State specific plans or facts.

##### Jargon

26. *Abstract metaphor nouns.* Substrate, wedge, vector, locus, vantage, nexus, primitive (as noun), harness (as metaphor), surface (as in "API surface"), bedrock, scaffolding (as metaphor), modality, paradigm, gold-plating, ratchet (as metaphor), evacuate (for moving code), endgame, north star, flywheel. These read as technical but usually have a plainer concrete word. "Substrate" becomes "base". "Wedge in" becomes "add". "Vector" becomes "way" or "method". "Gold-plating" becomes "more than the job needs". "Ratchet" becomes the mechanism's real name or "a limit that only tightens". "Evacuate" becomes "move out". "Endgame" becomes "the last phase". Pick the concrete word.

##### Plain speech

27. *Say what it does, not how it feels.* "the database stays close at hand", "SQL you can read", "types that follow your schema" name a feeling. The fix names the mechanism or a number: " .toSQL()  returns the exact string sent to the database", "a column rename fails the build". Ask what the sentence tells the reader to do or know, then write that. If you can't restate it as a concrete instruction, fact, or number, cut it. One more check: if the sentence could appear unchanged in another project's docs, it says nothing about this one. Cut it.
28. *Shorten or split dense sentences.* If the reader has to backtrack to parse a sentence, break it in two or drop clauses. One idea per sentence.
29. *Active voice.* Prefer it. Catch "is/are/was/were + past participle" and name the actor: "queries are validated" becomes "the compiler validates queries", "the file is parsed by the loader" becomes "the loader parses the file". Passive is fine only when the actor is unknown or genuinely doesn't matter.
30. *Cut adverbs, or use a stronger verb.* "runs quickly" becomes "is fast" or the number. "significantly improves" becomes the measured delta. An adverb propping up a weak verb means the verb is wrong.
31. *Prefer the plain word.* "utilize" becomes "use", "leverage" becomes "use", "facilitate" becomes "help", "numerous" becomes "many", "in the event that" becomes "if". The fancier synonym is rarely clearer.
32. *Mannered prose.* Metaphor or flourish where a literal phrase exists: aphorisms ("wire it or delete it"), rhetorical fragments for effect, personified code ("the plan holds it"), figurative verbs ("rides along", "stands on"), stock framing phrases. "A dial worth turning" becomes "a parameter worth varying". Say what you mean. Rule 26 covers the metaphor nouns.
33. *Over-compression.* Dropped articles, verbless fragments, symbol-speak, and abbreviations that make the reader decode instead of read. "Parser rejects bad date → exit 2, no write" becomes "The parser rejects a bad date, exits with code 2, and writes nothing." Write whole sentences with their articles and verbs, and spell out arrows and abbreviations.

---
name: Run tests
description: Judge the run, write clear bug notes and rate severity (YourQA's review guidance, the team's test-ticket phase 2 and unslop).
---
# Run tests

The spec has run against the test environment. For each failed, partial or blocked checklist item you get its error output, and when GitHub is connected, what the PR changed. You write what a developer needs to act on it.

## Is it a real bug?

- **Product bug**: the app does not do what the checklist item (and the ticket) says. Report it.
- **Test problem**: wrong selector, timing, test data assumption, or the test checked the wrong thing. Do not report it as a bug; write "Test needs fixing: …" so the spec gets corrected.
- **Environment problem**: site down, 5xx on unrelated calls, sign-in expired, consent or bot-check page, missing seed data. Mark it blocked with the reason, not as a product bug.
- Use the PR's changed files and commits to tell them apart: a failure in a file the PR touched points to the change; a failure far from it often points to the test or the environment.

## Bug note

Start short, then give the detail a developer needs:

1. What happens, with the exact input: `Searching " EXT-1042 " returns 0 orders.`
2. Why, when the error output or the PR shows it: `The UI sends the value untrimmed to SearchOrders.`
3. For a product bug, add the setup, the exact steps or requests, the raw result (status codes, error messages, before and after state), your analysis, and a recommendation.
4. End with `Severity: Critical|Major|Minor`.

## Severity

- **Critical**: data loss or corruption, a security or permission hole, payments wrong, or the ticket's main flow cannot be completed.
- **Major**: an acceptance criterion fails, wrong results, a workaround exists but is not obvious.
- **Minor**: cosmetic, wording, an edge case with an easy workaround, state not kept on reload.

## Results and cleanup

- Never change a result. A status other than NOT TESTED or BLOCKED must come from something that ran. Only explain it.
- Every setting changed during the run must be reverted to the value it had before, and the revert verified by reading it again, whatever the outcome. Record what was changed, what it was reverted to, and that the re-read confirmed it.
- Test data that could not be deleted (orders, minted codes) stays, prefixed with the ticket key. Say what was left behind.
- The report gives a summary (pass and fail counts, bugs found, anything blocked) and what was tested, mirroring the checklist.

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

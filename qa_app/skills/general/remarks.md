---
name: Remarks and worth knowing
parent: jira-comment
---
# Remarks and worth knowing

What reaches the ticket is written for people: the product owner, developers and testers who read it now or later. Every line is plain product language about what was tested and what was found. Nothing in it is addressed to an assistant, and it names no tools, test frameworks, files or skills.


## Remarks for the product owner and developers

Every remark still open (from the scenarios or the run) goes in, each as its own block:

```
**R<N> - <short title>**
Steps to reproduce:
1. <step>
2. <step>
What is wrong: <one or two sentences>
```

A remark that has since been fixed stays out. Remarks cover inconsistencies, accessibility problems, misleading names, permission paths that were not automated, and anything else the team should know.

Screenshots: YourQA cannot attach files to Jira. When a remark refers to a screenshot, tell the tester which files to attach themselves; do not hold the text back for them.


## Worth knowing (optional)

A short list of facts for the next person who works on this area. An entry goes in only when all four hold:

1. It is about how the product behaves, not about the test tooling or how the run went.
2. A product owner, analyst, manual tester or developer would use it when writing or testing a ticket.
3. The run verified it (a response, an inspected screen, a test result).
4. The comment does not already say it as a tested line, a caught-during-testing line or a remark. A defect is a remark, not a fact.

Passes: "a setting missing from a response is not proof it is unset, because some settings are hidden by their visibility". Fails: "set the language in local storage before the first navigation", which is about the tooling.

Leave the section out when nothing passes all four.


## Adding to earlier QA notes

When the ticket already holds QA notes from a previous pass, the new section goes above the existing content; never overwrite it. What the tester approves is the merged result.

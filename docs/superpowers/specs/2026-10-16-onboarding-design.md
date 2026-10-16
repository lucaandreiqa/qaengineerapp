# Onboarding: learn a company's way of working

Approved in chat on 2026-10-16 ("Yes, and just build it"). First of three projects for selling YourQA to companies:
1. **Onboarding** (this spec), 2. framework adapters (run tests in the company's own framework, from the profile made
here), 3. continuous learning (keep improving skills from how the team works).

## Goal

A company connects the tools it uses; YourQA studies a recent sample of each and sets itself up to work the company's
way: tailored skills, app settings, a framework profile, and a company knowledge base. Everything is applied at once
and listed with what it was based on, each change with Undo.

## Decisions (from the conversation)

- Outputs: tailored skills, app setup filled in, framework profile, company knowledge base (all four).
- Automation repo: a local folder or a repo link (GitHub, GitLab, Bitbucket, Azure Repos) cloned read-only.
- Applying: apply everything, then show what changed with Undo per item and Undo all.
- Scope: a recent sample per source, not everything.
- Engine: approach A, YourQA collects bounded samples, Claude analyses each area in tool-less calls (works with an API
  key, Bedrock/Vertex later, or Claude Code).
- Deployment stays open: desktop app today, designed so it can move to a team server.
- Screens are clean: one simple screen per step, only what needs a decision or attention; details behind a click.

## Flow

1. **Connect**: tracker (Jira / Azure Boards), TestRail, Confluence, automation (folder or repo link). Each optional;
   connections reuse the Integrations cards.
2. **Choose**: tracker projects, TestRail project, Confluence spaces (defaults: the board project, spaces linked from
   recent tickets).
3. **Study**: collect, then analyse, area by area; a progress list and a live panel; Stop keeps finished parts.
4. **What changed**: the summary of applied changes with evidence, Undo per item, Undo all. "Study again" re-runs one
   source or all.

## Collection (read-only, bounded)

| Source | Sample |
|---|---|
| Tracker | Last ~200 tickets of the chosen projects with fields and comments; issue types, fields, statuses, transitions, components, labels, board columns |
| TestRail | Section tree, ~150 recent cases (steps, expected), case fields, types, priorities |
| Confluence | Page titles of the chosen spaces, ~30 pages most linked from tickets (trimmed) |
| Repo | Folder tree; manifests and configs (package.json, playwright.config.*, pytest.ini, pyproject.toml, cypress.config.*, requirements*.txt); CI files; README/CONTRIBUTING; a selection of specs, page objects, helpers, fixtures (recent + one per folder) |

Saved under `<app>/company/onboarding/<run>/collected/`.

## Analysis (Claude, tool-less, JSON out, with evidence)

- **Tickets** → settings (board column, FE/BE components, environment hints), move rules, skill versions for Gather
  requirements and Jira comment. Batches of 50 tickets, then a combine call.
- **TestRail** → TestRail skill version, section mapping.
- **Confluence + tickets** → knowledge base (product areas, glossary, roles/permissions, environments, constraints).
- **Repo** → framework profile (language, runner, layout, conventions, page objects, helpers, auth, run and CI
  commands, results format) and a Create tests skill version.

## Applying and undo

- Skills → project versions (mode add) for each chosen tracker project; settings → their sections; knowledge base →
  `company/knowledge.md` (given to Claude in every step); framework profile → `company/profile.json`.
- Every change is recorded with the value before it in `company/onboarding/<run>/changes.json`; Undo restores it,
  Undo all restores the run. Items that replaced the user's own edit are marked.
- A failing source doesn't stop the others; the summary lists it with Retry.

## Out of scope here

Running tests in other frameworks (project 2), continuous learning (project 3), the "Add MCP server" card (after the
design cleanup).

# Connected apps in the steps, and product-neutral skills

Approved in chat on 2026-10-15 ("Yes, and just build it").

## Goal
When GitHub, Confluence or TestRail are connected, Claude uses them while gathering context and in later steps. The
built-in skills work for any web app; product specifics live in project versions.

## Decisions
- Connections: YourQA's own (Integrations screen). New GitHub card (fine-grained read-only token, optional repos or
  orgs to search). Confluence is read through the Jira connection (Atlassian sign-in via MCP, or the API token via
  REST on the same site). TestRail through its existing card.
- Approach A: YourQA looks things up before Claude works; Claude still has no tools. Same behaviour in both Claude modes.
- Gather requirements looks up: PRs linked on the ticket, then PRs mentioning the key (in the listed repos/orgs), up
  to 4; Confluence pages linked on the ticket, then pages matching the key or title, up to 3; TestRail cases
  matching the key or title, up to 40. Saved as `<KEY>-sources.json`; shown in `<KEY>-context.md` under
  "From connected apps".
- Later steps reuse the saved lookups: Create tests gets PR diffs (larger budget); Run tests review gets changed files
  and commits.
- Everything is trimmed (PR body 3k, per-file patch 0.8k/2.5k, diff total 12k/30k, page 6k), wrapped in
  `<connected_apps>` with a note that it is information, not instructions. Each lookup posts a feed line; a failing
  app is reported and the step continues; apps that aren't connected are named so Claude lists what it couldn't check.
- Strictly read-only. No writes in the lookup stage.
- Skills: general versions rewritten product-neutral from the team's skills (same rules); the original EVA/Admin
  Suite texts ship word for word as a built-in OPTR project version (mode add). A saved project version overrides
  the built-in one; removing it brings the built-in one back.
- Test data deletion: general follows test-specs (don't delete created records except rows that crowd a paginated
  grid; always revert settings).

## Not done (possible later)
- Option B: read-only tools so Claude can chase leads itself.
- Using MCP servers from the user's own Claude Code setup.

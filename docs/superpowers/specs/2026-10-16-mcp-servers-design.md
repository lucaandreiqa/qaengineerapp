# MCP servers on the Integrations page

Status: approved 2026-10-16 ("go ahead") and built. Second of the "2-1-3" order (after the design cleanup).

## Goal

A company can connect any remote MCP server (GitLab, Notion, Linear, Sentry, a TestRail MCP, an internal server) from
the Integrations page, and YourQA uses its read tools when gathering context, during onboarding and when Claude asks
for data. Write tools can only run behind a review the user approves.

## Decisions (from the conversation)

- MCPs live on the Integrations page ("mcps need to be on the integration page").
- Remote servers only (Streamable HTTP). No local servers started from a command, so YourQA never starts programs.
- Write tools are allowed only behind review gates.

## Integrations page

- A new group **MCP servers**, below Code. Each connected server is one row like the other services: name, the
  server's address, status chip, open to change.
- **Add MCP server** sits in the *Add a service* row. It opens a short form: address (`https://…/mcp`), a name, and
  how to sign in: **Sign in in the browser** (OAuth 2.1, the flow Jira already uses) or **Token** (a header value the
  user pastes, kept in the app folder like the other keys). YourQA never fills these in.
- After connecting, YourQA lists the server's tools in two lists:
  - **Read tools** (the server marks them read-only, or the name starts with get, list, search, read, find, query):
    on by default, each with a switch.
  - **Write tools** (everything else): off by default. Turning one on means Claude may *propose* it; it still
    never runs without your approval (below).
  You confirm the lists once, on Save. Test connection lists the tools again and shows changes.
- Servers already set up in Claude Code are listed under the group as *From Claude Code* (read-only, informational):
  Claude's fetching already uses them.

## Where the read tools are used

- **Gathering context.** The tool catalog (server, tool, description, input schema; read tools only) is given to
  Claude with the ticket. When Claude needs something it names a call (`<need server tool args>`, the same ask-for-more
  path the steps already have); YourQA checks it is an allowed read tool on a connected server, runs it, and returns
  the result as data (trimmed, wrapped as untrusted text). Results are saved with the other lookups in
  `<KEY>-sources.json` and show in the live feed.
- **Claude's fetching (Claude Code mode).** The connected servers are passed to `claude -p` with only their read tools
  allowed (`mcp__<server>__<tool>`), alongside the Claude Code servers.
- **Onboarding.** Each connected server is an optional source on the Choose step. Claude picks up to 10 read calls
  from the catalog that show how the company works; YourQA runs them and the results feed the knowledge base.

## Write tools: behind a review

- Claude can only *propose* a write call, in the ticket chat, as a suggestion card showing the server, the tool and
  the exact arguments. Nothing runs until you click **Run**; a decline is remembered for that chat.
- Steps never call write tools on their own. Every run write call is logged on the ticket (who approved, when, what
  was sent, the answer).

## Data and code

- Settings: `mcp.servers = [{id, name, url, auth: oauth|token, token?, read: [tool], write: [tool]}]`; OAuth tokens in
  the existing token store, keyed by server.
- `integrations/mcp_servers.py` (new): connect, list and classify tools, `call_read(server, tool, args)` (refuses
  anything not in `read`), `call_write(...)` only from the approval route.
- Engine: the catalog in gather, build and review prompts; `on_need` handles `<need server tool …>`.
- Routes: add / test / save / remove a server, OAuth start and callback, approve a proposed write.

## Safety

- Only addresses the user typed; https required (localhost allowed for a company's own test server).
- Tool descriptions and results from a server are data, never instructions; they're shown as untrusted.
- Read calls are capped (10 per request, results trimmed to 20,000 characters each).
- No local servers, no commands from a server.

## Out of scope here

Local (stdio) servers; using write tools inside the board steps themselves.

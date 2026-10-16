# Sign-in and first-run setup

Status: agreed in chat on 2026-10-16 and built.

## Decisions (from the conversation)

- When the app opens, a sign-in screen comes first. Google sign-in for now; any Google account can sign in (it says who
  is using YourQA).
- Google sign-in uses **YourQA's own Google OAuth client**, shipped with the app (a Desktop app client, made once in
  Google Cloud). The client ID and secret are read from `qa_app/google_client.json` (not in git) or the environment
  (`QA_APP_GOOGLE_CLIENT_ID`, `QA_APP_GOOGLE_CLIENT_SECRET`). A build without a client says so on the sign-in screen
  and offers **Continue without signing in**: sign-in identifies people and isn't a lock, since any Google account may
  sign in.
- After signing in, a first-run **setup** walks through one page per connection, each skippable: Claude; tracker (Jira
  or Azure Boards); test cases (TestRail, Zephyr Scale or Xray); code and tools (GitHub, MCP servers); automation
  repo; notifications (Slack or Teams). The last page lists what's connected and **starts onboarding's study** with one
  click, then opens the board.

## Sign-in

- `qa_app/auth.py`: the Google authorization code flow with PKCE, the redirect on `http://127.0.0.1:<port>/api/auth/google/callback`
  (loopback, as Google allows for desktop clients). The code is exchanged server to server; the ID token from the token
  endpoint is checked for audience, issuer, expiry and a verified email.
- A session is a random token in an HttpOnly, SameSite=Lax cookie (`yourqa_session`), 30 days; only its SHA-256 is
  stored, in `<app>/sessions.json`. Sign out deletes it.
- Every `/api/...` route needs a session, except sign-in itself and the OAuth callbacks of Jira and MCP servers (they're
  protected by their own one-time state). Without one the API answers 401 and the app shows the sign-in screen.
- `QA_APP_AUTH=off` turns sign-in off (CI, tests).
- The signed-in person shows at the bottom of the sidebar with Sign out; MCP writes they run record their email.

## Setup

- Route `#/setup/<page>`; full screen, no sidebar; progress dots; Back, Skip and Continue on every page.
- Pages reuse the existing connection forms (Jira link and sign-in, Azure link and token, the integration cards, the
  MCP server form), so a connection made here is the same as on Integrations, and a good connection test switches it on.
- Shown after sign-in until finished or skipped (`app.setup_done` in settings); **Set up again** on the Onboarding screen
  reopens it.
- Finish: the projects to study (default: the board's project) and **Start studying** → `POST /api/onboarding/study`
  with what's connected, then the board.

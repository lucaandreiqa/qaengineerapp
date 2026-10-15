# YourQA: working on this repo

## Documentation is part of every change

- `docs/ARCHITECTURE.md` describes how the app is built. Whenever you implement something that adds or changes a
  module, a data flow, a connection to another app, a file on disk, a setting, or a safety rule, update the matching
  section of `docs/ARCHITECTURE.md` in the same commit, bump its "Last updated" line, and add a line to its decisions log.
- User-facing behaviour goes in `README.md` as well.
- Designs agreed with the user are saved in `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`.
- A change isn't finished until the docs match the code.

## How we work

- Tests first for behaviour changes; run the affected suites before committing.
- Never enter credentials for the user; they enter their own on the Integrations screen.
- Anything that writes to Jira, TestRail or other shared systems happens only behind the user's review gates.
- Lookups and Claude's fetching stay read-only.

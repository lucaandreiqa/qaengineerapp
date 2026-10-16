# Framework adapters: tests in the company's style

Status: approved 2026-10-16 ("yes") and built. Project 2 of 3 for selling YourQA to companies (after onboarding,
before continuous learning).

## Decisions (from the conversation)

- First version: **Playwright (TypeScript/JS)** only, the framework YourQA already runs. Other frameworks come later
  through the same adapter seam.
- Tests are written in **YourQA's own workspace**, copying the company's style but never importing their code.
- When a ticket is done its tests are **kept on a local branch** (`yourqa/<KEY>`). YourQA never pushes.

## What changes for a ticket

1. **Create tests** writes the spec the way the company writes theirs. Claude gets, besides the checklist and the
   Create tests skill (already tailored by onboarding):
   - the framework profile (`company/profile.json`, already used today);
   - **style examples**: up to 2 of the company's own spec files and the signatures of their page objects and
     helpers, taken from the last onboarding study of the automation repo (trimmed to 12,000 characters). They show
     naming, structure, tags, locator style, fixtures and test data. Claude copies the patterns and writes them inline
     (or as small local helpers next to the spec); it never imports from the company's repo.
2. **Run tests** is unchanged: YourQA's own config and reporter, the ticket's environment, the saved SSO session.
3. **When the ticket is done** (pushed to TestRail, or finished another way), YourQA commits the ticket's folder
   (`tests/tickets/<KEY>/`: specs, checklist, scenarios, report) to the branch `yourqa/<KEY>` in the workspace, one
   commit per finish, message `QA <KEY>: <title> (n passed, m failed)`. It's done with git plumbing (a temporary
   index), so the workspace's checked-out branch and files are never touched. A workspace that isn't a git repository
   is initialised only when it's YourQA's default workspace; a folder you chose yourself that isn't a repository is
   left alone and the feed says the tests weren't kept on a branch.

## When the company uses another framework

The profile says so (Cypress, pytest, Selenium…). YourQA still writes Playwright TypeScript in its workspace, borrowing
what carries over (structure, naming, test data, how they sign in), and says once in the ticket feed which framework
the company uses and that YourQA ran Playwright. Adding a real adapter for it later doesn't change the board.

## The adapter seam

`qa_app/frameworks/`:
- `base.py`: `Adapter` with `name`, `matches(profile) -> bool`, `style_examples(company_dir) -> str`,
  `spec_files(key) -> list[str]`, and `run(...)` (the existing Playwright run).
- `playwright_ts.py`: the one adapter now, wrapping `playwright_run`.
- `pick(profile) -> (adapter, note)`: the matching adapter, or Playwright TS with a note when nothing matches.
- `keep.py`: `commit_ticket(workspace, key, message) -> str` (the branch commit, plumbing only).

## Safety

- YourQA never pushes, never checks out a branch in the workspace, and never runs a command taken from the company's
  repo or profile.
- Style examples are the company's own files, read during onboarding; they're data for Claude, not instructions.

## Out of scope here

Other frameworks (Cypress, Python pytest-playwright, Selenium), running the company's own config or commands, opening
pull requests.

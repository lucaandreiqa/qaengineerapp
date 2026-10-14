# QA Engineer App

A desktop app (Python + Playwright + PySide6) that tests websites for you. Give it a URL and it crawls
the site, runs the checks you pick, and produces an HTML report plus JUnit XML. It can push results
to Jira, Slack, Teams, TestRail, Xray, Zephyr Scale and AWS S3, and the same engine runs headless in
CI.

## Checks

| Check | What it does |
|---|---|
| **Functional** | Crawls same-site pages (up to *Max pages*), flags HTTP errors, page load failures, uncaught JS exceptions, console errors, failed resource requests, broken internal/external links |
| **Visual regression** | Full-page screenshots per viewport (desktop / tablet / mobile), pixel diff against stored baselines, highlighted diff images |
| **Accessibility** | axe-core WCAG 2.1 A/AA + best-practice rules on every page |
| **SEO** | Title, meta description, h1, lang, viewport, canonical, noindex, missing alt text |
| **Performance** | Navigation timing and page weight on every page, plus Google Lighthouse (performance, a11y, best practices, SEO, LCP, CLS) on the first 3 pages. Lighthouse needs Node.js |

Severity: **critical** / **major** fail the run; **minor** / **info** are reported only.

## Setup (Windows)

```bat
setup.bat      :: one-time: venv + packages + Chromium
run_app.bat    :: start the desktop app
```

Or manually: `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`,
`.venv\Scripts\python -m playwright install chromium`, `.venv\Scripts\python -m qa_app`.

## Desktop app

- **Run**: enter a URL, pick checks and viewports, then Run. Findings stream in live. Click one to see details and the screenshot or visual diff.
- **History**: every past run. Open its report or folder, or publish it to integrations after the fact.
- **Integrations**: configure each service, click *Test connection*, then Save.

Data lives in `%USERPROFILE%\.qa_app\` (`runs/`, `baselines/`, `settings.json`).
To accept intended UI changes, tick *Accept current screenshots as new baselines* and run again.

## Integrations

| Service | What happens | Needs |
|---|---|---|
| Jira Cloud | One bug per finding at or above *min severity*, deduplicated across runs (a hidden label tracks it), screenshot attached | base URL, email, [API token](https://id.atlassian.com/manage-profile/security/api-tokens), project key |
| Slack | Run summary + top issues + report button | Incoming webhook URL |
| Teams | Same, as an Adaptive Card | Workflows / incoming webhook URL |
| TestRail | Auto-creates a test case per (check, page), creates a run, posts pass/fail with linked Jira defects | URL, user, API key, project id (suite id for multi-suite projects) |
| Xray Cloud | Imports JUnit as a Test Execution | client id/secret, project key |
| Zephyr Scale | Imports JUnit as a test cycle, auto-creating test cases | API token, project key |
| AWS S3 | Uploads the whole run folder. The report link (presigned for 7 days, or via `public_base_url`) is shared in Slack/Teams/Jira | Standard AWS credentials (profile, SSO, env, role) |

Any setting can be overridden with an env var: `QA_APP_<SECTION>_<KEY>`, e.g. `QA_APP_JIRA_API_TOKEN`.
Use env vars for secrets in CI.

## CLI / CI

```bash
python -m qa_app.cli https://example.com --checks all --max-pages 25 --publish --out qa-results
```

Options: `--checks functional,visual,accessibility,seo,performance|all`, `--viewports desktop,tablet,mobile`,
`--fail-on critical|major|minor|never` (exit code 1 when matched), `--publish [jira,slack,…]`,
`--update-baselines`, `--no-lighthouse`, `--headed`.

Ready-made pipelines in [`ci/`](ci/): GitHub Actions, GitLab CI, Bitbucket Pipelines. All three publish
JUnit to the platform's test view and keep the HTML report as an artifact. On GitHub a summary table is
also written to the job page.

## Project layout

```
qa_app/
  __main__.py        desktop entry point (python -m qa_app)
  cli.py             headless entry point for CI
  runner.py          crawl + orchestrate checks
  checks/            functional, visual, accessibility, seo, lighthouse
  integrations/      jira, slack, teams, testrail, xray, zephyr, aws_s3
  report.py          HTML + JUnit output
  ui/                PySide6 window and background workers
ci/                  pipeline templates
```

# Design brief: YourQA

Paste this into Claude Design (claude.ai/design) as the starting prompt.

---

Design a desktop app for a QA engineer that automatically tests websites. Window size is about
1400×860 and it needs to work down to 1100 wide. It should look like a modern developer tool
(Linear, Vercel or Raycast quality), dense but calm, with **dark and light themes**. Output HTML/CSS.

## Screens

### 1. Run (main screen)
- **URL input**, large and prominent, with a primary **Run tests** button. While running it turns into **Stop**.
- **Check toggles** (each with an icon and a one-line description):
  Functional (crawl, JS errors, broken links) · Visual regression · Accessibility (WCAG) · SEO · Performance (Lighthouse).
- **Options** (collapsible): max pages (number), viewports (desktop / tablet / mobile chips),
  visual diff threshold (%), use Lighthouse, accept new baselines, show browser window,
  publish to integrations after run.
- **Live progress**: pages crawled X / Y, current URL, elapsed time.
- **Results**:
  - Summary bar with PASSED or FAILED status, counts by severity (critical, major, minor, info), pages tested, duration.
  - Findings list that streams in live, with columns: severity chip · check · title · page URL. Filter by severity and by check, plus search.
  - Selecting a finding opens a **detail panel**: title, severity, check, page, details text (can be monospace / long), screenshot or visual-diff image (click to enlarge), and a "Create Jira issue" action.
  - Log console (collapsible, monospace).
  - "Open full report" button.
- States: empty (no run yet), running, passed, failed, error.

### 2. History
Table of past runs with columns: date/time, URL, PASSED/FAILED, critical / major / minor counts, duration.
Row actions: open report, open folder, publish to integrations. A small trend chart of issues over time per site would be nice.

### 3. Integrations
A card per integration with a logo-ish icon, enabled toggle, connection-status dot, settings form,
**Test connection** button with an inline success/error result, and Save:
- Jira: base URL, email, API token, project key, issue type, min severity
- Slack: webhook URL, only on failure
- Microsoft Teams: webhook URL, only on failure
- TestRail: base URL, username, API key, project id, suite id
- Xray: client id, client secret, project key
- Zephyr Scale: API token, project key
- AWS S3: bucket, prefix, region, profile, public base URL
Secret fields are masked with a reveal toggle.

### 4. HTML report (standalone page, opened in a browser and shareable)
Same visual language: header with site, run id and status, severity counts, filterable findings
with screenshots, Lighthouse score gauges (performance, accessibility, best practices, SEO, LCP, CLS),
and a table of the pages crawled.

## Navigation
Left sidebar with app name/logo, Run, History, Integrations, and a theme toggle at the bottom.

## Severity colours (keep consistent everywhere)
critical = red · major = orange · minor = amber · info = slate · passed = green

## Deliverable
Export HTML/CSS and drop the files into `design/` in this project, or share the link or screenshots.

# General and personal skills

Date: 2026-10-26. Agreed with Luca.

## What he asked for

> GENERAL skills = a tree of skills that can be applied on each project/product, not editable. PERSONAL skills = a
> specialised skill tree made of general skills + what we learned from onboarding (very important), editable. The user
> should be able to choose from these what to use on their project; we should say personal might be the best option.

He also supplied a set of improved skills (from the EVA Admin Suite work) to base the general tree on.

## Design

### Two trees, one shape

- `qa_app/skills/general/tree.json` lists the five board steps and the skills under each:
  - Gather requirements: Ticket context, Scenarios, QA checklist
  - Create tests: Spec conventions, Locators and page structure, Test data, UI timing
  - Run tests: Why a check failed, Bug notes
  - Jira comment & move: QA summary, Remarks, Plain writing
  - Update TestRail tests: Writing cases, Manual cases and automation
- Each skill is one Markdown file with front matter (`name`, `parent`).
- A step sends Claude its own skill followed by every skill under it.

### General skills

- Ship with the app.
- Product-neutral: rewritten from the supplied skills with every product name, URL, person and internal helper taken
  out.
- Read-only: no route or code path writes them.

### Personal skills

- Live in `~/.qa_app/skills/personal/`, in the same shape as the general tree.
- Editable on the Skills screen; each skill resets to its general version.
- A skill missing from the personal tree falls back to the general one.
- Ways the personal tree gets made:
  - **Finish onboarding**, the recommended way;
  - **Copy the general skills**;
  - the first save of a skill;
  - a learned move rule.

### Choice per project

- `skills.choice` in settings holds `{KEY: personal|general}`.
- Personal is recommended: it is the default once the personal tree exists, and the Skills screen marks it
  *Recommended*.
- The empty Personal tab says that finishing onboarding is the best way to make it.

### Onboarding builds the personal tree

- **During the study:**
  - Skill lessons are only recorded; nothing is written to any skill.
  - Move rules go into the personal Jira comment skill.
- **Finish:**
  - Copies the general tree into personal; an existing personal tree is kept.
  - For each step with kept lessons, one Claude call gets the current text of every skill in the step's branch plus
    the lessons, and returns the whole improved text of the skills those lessons bear on. Conventions are worked in
    where they belong, not in a separate section.
  - The studied projects switch to personal.
  - If Claude fails, the lessons are appended to the step's own skill as they are.
- **The finished page:**
  - Lists each changed skill, grouped by step, with the lines it gained.
  - Accept or Revert per skill. Revert restores the personal skill as it was before Finish, or the general text if
    there was none, but only while nobody has edited it since.

### Migration

On startup, edits in the old `skills/general/` and `skills/projects/<KEY>/` folders:

- are appended to the matching personal skills;
- then the old folders are moved to `skills/_before-personal/`.

Nothing the user wrote is lost. The built-in OPTR project version is retired.

## Out of scope

- Several personal trees, for example one per project.
- Adding or removing skills in the tree from the UI.

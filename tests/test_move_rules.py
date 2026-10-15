from qa_app.workflow import move_rules as mr
from qa_app.workflow.models import CheckItem


def items(*results):
    return [CheckItem(text=f"check {i}", result=r) for i, r in enumerate(results)]


def test_a_run_is_grouped_into_one_of_three_results():
    assert mr.outcome(items("pass", "pass")) == "passed"
    assert mr.outcome(items("pass", "fail", "blocked")) == "failed"
    assert mr.outcome(items("pass", "partial")) == "incomplete"
    assert mr.outcome(items("pass", "blocked", "nt")) == "incomplete"


def test_a_rule_is_added_to_its_own_section_and_the_rest_of_the_skill_is_kept():
    skill = "# Jira comment\n\nWrite short comments.\n\n## Tone\n\nPlain words."
    out = mr.with_rule(skill, "failed", "To Do")
    assert out.startswith(skill)  # the user's own text is untouched
    assert "## Moving the ticket" in out and '- When any check fails: move to "To Do".' in out
    assert mr.rules(out) == {"failed": "To Do"}
    out2 = mr.with_rule(out, "passed", "Done")
    out3 = mr.with_rule(out2, "failed", "Reopened")  # replaces, never duplicates
    assert mr.rules(out3) == {"failed": "Reopened", "passed": "Done"}
    assert out3.count("## Moving the ticket") == 1 and out3.count("When any check fails") == 1
    assert out3.startswith(skill)


def test_the_skill_picks_a_state_only_when_jira_offers_it():
    skill = mr.with_rule("", "failed", "To Do")
    assert mr.pick(skill, "failed", ["To Do", "Done"]) == "To Do"
    assert mr.pick(skill, "failed", ["Reopened", "Done"]) == ""  # not offered for this ticket
    assert mr.pick(skill, "passed", ["To Do", "Done"]) == ""     # no rule for this result
    assert mr.pick(skill, "failed", ["to do"]) == ""             # names are matched exactly, as in the move itself

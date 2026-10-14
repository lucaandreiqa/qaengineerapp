"""Finding the test environment from what the ticket says, for any team (no company-specific rules)."""
from __future__ import annotations

from qa_app.workflow import agent, environments as envs
from qa_app.workflow.settings import WorkflowConfig as Config


def ctx(**kw):
    base = {"description": "", "environment": "", "fields": {}, "web_links": [], "comments": [], "status": "In Review",
            "acceptance_criteria": ""}
    base.update(kw)
    base["comments"] = [c if isinstance(c, dict) else {"body": c, "author": "Dev"} for c in base["comments"]]
    return base


def best(c, **kw):
    found = envs.find(c, **kw)
    app, api = envs.choose(found, kw.pop("ticket_type", "") if "ticket_type" in kw else "")
    return (app.url if app else None), (api.url if api else None), found


def test_common_ways_teams_post_the_environment():
    cases = {
        "Deployed to https://feature-123.preview.acme.dev": "https://feature-123.preview.acme.dev/",
        "Preview: https://acme-git-fix-cart-acme.vercel.app/cart": "https://acme-git-fix-cart-acme.vercel.app/cart",
        "Ready for QA on staging → https://staging.shop.io/": "https://staging.shop.io/",
        "you can test it here: https://pr-481.myapp.netlify.app": "https://pr-481.myapp.netlify.app/",
        "Review app (https://review-42.herokuapp.com).": "https://review-42.herokuapp.com/",
        "[Test env|https://qa.internal.acme.com/login]": "https://qa.internal.acme.com/login",
        "env: https://uat.bank-demo.eu": "https://uat.bank-demo.eu/",
    }
    for text, want in cases.items():
        assert best(ctx(comments=[text]))[0] == want, text


def test_noise_links_are_not_environments():
    c = ctx(description="Design https://www.figma.com/file/abc and spec https://acme.atlassian.net/wiki/x and "
                        "code https://github.com/acme/web/pull/12 screenshot https://cdn.acme.com/shot.png",
            comments=["See https://docs.google.com/document/d/1", "Sentry https://acme.sentry.io/issues/9"])
    assert envs.find(c, jira_host="acme.atlassian.net") == []


def test_newest_comment_wins_and_unclear_links_are_offered_not_used():
    c = ctx(comments=[{"body": "Deployed to https://pr-1.preview.acme.dev", "author": "Ana", "created": "2026-10-10"},
                      {"body": "Redeployed after the fix: https://pr-2.preview.acme.dev", "author": "Ben", "created": "2026-10-14"}])
    app, _, found = best(c)
    assert app == "https://pr-2.preview.acme.dev/" and found[0].source == "comment by Ben · 2026-10-14"
    c = ctx(description="Customers reported it on https://www.acme.com/checkout")  # production, no env words
    app, _, found = best(c)
    assert app is None and found and found[0].prod  # listed for the user, never used on its own
    c = ctx(description="Related: https://example.org/page")  # just a link
    assert best(c)[0] is None and envs.find(c)


def test_environment_field_custom_fields_web_links_and_hints():
    assert best(ctx(environment="https://test7.acme.io"))[0] == "https://test7.acme.io/"
    assert best(ctx(fields={"Preview URL": "https://abc.acme.io"}))[0] == "https://abc.acme.io/"
    assert best(ctx(web_links=[{"title": "Staging", "url": "https://acme-stg.io/"}]))[0] == "https://acme-stg.io/"
    plain = ctx(comments=["https://box-17.acme-internal.net"])  # nothing says it's an env…
    assert best(plain)[0] is None
    assert best(plain, hints=["acme-internal.net"])[0] == "https://box-17.acme-internal.net/"  # …unless the team says so


def test_api_links_pair_with_the_app_or_lead_for_backend_tickets():
    c = ctx(comments=["Deployed: app https://pr-9.preview.acme.dev , API https://api.pr-9.preview.acme.dev"])
    found = envs.find(c)
    assert envs.choose(found, "FE")[0].url == "https://pr-9.preview.acme.dev/"
    assert envs.choose(found, "FE")[1].url == "https://api.pr-9.preview.acme.dev/"
    assert envs.choose(found, "BE")[0].url == "https://api.pr-9.preview.acme.dev/"


def test_resolve_uses_default_only_for_merged_or_done_and_lists_candidates():
    cfg = Config(demo=False, default_env_url="https://staging.acme.dev/", default_env_name="staging")
    issue = {"merged": False, "type": "FE", "context": ctx(status="Done", comments=["old preview https://pr-1.preview.acme.dev"])}
    env, _ = agent.resolve_environment(issue, cfg)
    assert env.shared and env.url == "https://staging.acme.dev/" and env.kind == "staging · ticket is done"
    issue = {"merged": False, "type": "FE", "context": ctx(status="In Review", description="See https://example.org/a and https://example.org/b")}
    env, reason = agent.resolve_environment(issue, cfg)
    assert env is None and reason.startswith("Found 2 links") and [c["url"] for c in issue["env_candidates"]] == \
        ["https://example.org/a", "https://example.org/b"]
    issue = {"merged": False, "type": "FE", "context": ctx(comments=[{"body": "Deployed https://pr-5.preview.acme.dev", "author": "Ana"}])}
    env, _ = agent.resolve_environment(issue, cfg)
    assert env.url == "https://pr-5.preview.acme.dev/" and env.source == "comment by Ana" and not env.shared

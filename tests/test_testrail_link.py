import pytest

from qa_app.integrations import testrail


def test_any_testrail_page_link_gives_the_site_and_what_it_names():
    p = testrail.parse_link
    assert p("https://acme.testrail.io/index.php?/projects/overview/3") == {"base_url": "https://acme.testrail.io", "project_id": "3"}
    assert p("acme.testrail.io/index.php?/suites/view/12&group_by=cases:section_id") == {"base_url": "https://acme.testrail.io", "suite_id": "12"}
    assert p("https://acme.testrail.io/index.php?/cases/view/4512") == {"base_url": "https://acme.testrail.io", "case_id": "4512"}
    assert p("https://acme.testrail.io/index.php?/runs/view/88") == {"base_url": "https://acme.testrail.io", "run_id": "88"}
    assert p("https://qa.example.com/testrail/index.php?/dashboard") == {"base_url": "https://qa.example.com/testrail"}
    assert p("https://acme.testrail.io/") == {"base_url": "https://acme.testrail.io"}


class FakeTR:
    def __init__(self, projects):
        self.projects, self.asked = projects, []

    def __call__(self, cfg):
        self.cfg = cfg
        return self

    def get(self, path):
        self.asked.append(path)
        if path.startswith("get_suite/12"):
            return {"id": 12, "project_id": 7}
        if path.startswith("get_case/4512"):
            return {"id": 4512, "suite_id": 12}
        if path.startswith("get_run/88"):
            return {"id": 88, "project_id": 7, "suite_id": 12}
        if path.startswith("get_projects"):
            return {"projects": self.projects}
        if path.startswith("get_project/"):
            pid = int(path.split("/")[1])
            return next(p for p in self.projects if p["id"] == pid)
        raise KeyError(path)


@pytest.fixture()
def fake(monkeypatch):
    f = FakeTR([{"id": 7, "name": "Admin Suite"}, {"id": 9, "name": "POS"}])
    monkeypatch.setattr(testrail, "_client", f)
    return f


def test_the_project_comes_from_the_link_or_from_testrail(fake):
    base = {"username": "qa@acme.com", "api_key": "k"}
    assert testrail.resolve({**base, "base_url": "https://acme.testrail.io/index.php?/projects/overview/9"})["project_id"] == "9"
    r = testrail.resolve({**base, "base_url": "https://acme.testrail.io/index.php?/suites/view/12"})
    assert (r["base_url"], r["project_id"], r["suite_id"]) == ("https://acme.testrail.io", "7", "12")
    r = testrail.resolve({**base, "base_url": "https://acme.testrail.io/index.php?/cases/view/4512"})
    assert (r["project_id"], r["suite_id"]) == ("7", "12")
    r = testrail.resolve({**base, "base_url": "https://acme.testrail.io/index.php?/runs/view/88"})
    assert (r["project_id"], r["suite_id"]) == ("7", "12")
    assert testrail.resolve({**base, "base_url": "https://acme.testrail.io", "project_id": "9"})["project_id"] == "9"  # typed wins


def test_with_one_project_it_is_used_and_with_several_you_are_told_which_exist(fake, monkeypatch):
    base = {"username": "qa@acme.com", "api_key": "k", "base_url": "https://acme.testrail.io"}
    with pytest.raises(testrail.TestRailError) as e:
        testrail.resolve(base)
    assert "Admin Suite (7)" in str(e.value) and "POS (9)" in str(e.value)
    monkeypatch.setattr(testrail, "_client", FakeTR([{"id": 7, "name": "Admin Suite"}]))
    assert testrail.resolve(base)["project_id"] == "7"


def test_connection_says_which_project_and_returns_the_filled_in_fields(fake):
    text, values = testrail.check({"username": "qa@acme.com", "api_key": "k", "base_url": "https://acme.testrail.io/index.php?/suites/view/12"})
    assert "Admin Suite" in text and values == {"base_url": "https://acme.testrail.io", "project_id": "7", "suite_id": "12"}


def test_the_board_works_out_a_missing_project_and_remembers_it(fake, monkeypatch):
    """Saved from a suite link: suite_id set, project_id empty (as on the Mac, 2026-10-15)."""
    from qa_app.workflow import clients
    saved = {}
    monkeypatch.setattr(clients, "_remember_testrail", lambda fields: saved.update(fields))
    cfg = {"base_url": "https://acme.testrail.io", "username": "qa@acme.com", "api_key": "k", "project_id": "", "suite_id": "12", "enabled": True}
    tr = clients.RealTestRail(cfg)
    assert tr.cfg["project_id"] == "7" and saved == {"project_id": "7"}   # found through the suite, and saved for next time
    with pytest.raises(clients.WorkflowError) as e:
        clients.RealTestRail({**cfg, "username": ""})
    assert "username" in str(e.value)


def test_case_search_works_without_a_saved_project(fake):
    seen = []
    fake.get = (lambda orig: (lambda path: (seen.append(path), {"cases": [{"id": 1, "title": "x", "section_id": 2}]} if path.startswith("get_cases") else orig(path))[1]))(fake.get)
    out = testrail.search_cases({"base_url": "https://acme.testrail.io", "username": "u", "api_key": "k", "project_id": "", "suite_id": "12"}, "OPTR-1")
    assert out[0]["id"] == 1 and any(p.startswith("get_cases/7") for p in seen)

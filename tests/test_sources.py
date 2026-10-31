from datetime import datetime, timedelta, timezone

from hunter import sources
from hunter.pipeline import board_windows


def _stub(monkeypatch, cand, capped_term="marketing digital", block_after=None):
    cand.config["searches"] = ["growth marketing", "marketing digital"]
    cand.config["sources"].update(linkedin=True, indeed=True, hellowork=True, glassdoor=True)  # off by default
    cand.config["scraping"]["pause_between_searches_s"] = [0, 0]
    calls = []

    def listing(site, term, location, hours, n):
        calls.append((site, term, location, hours))
        if block_after and len(calls) > block_after:
            sources.WATCH.blocked.add(site)
            return []
        capped = term == capped_term and location == "France"
        return [sources.job(id=f"{site}:{len(calls)}:{i}", title="x") for i in range(n if capped else 3)]

    monkeypatch.setattr(sources, "listing", listing)
    return calls


def test_home_search_is_skipped_when_france_returned_everything(monkeypatch, cand):
    calls = _stub(monkeypatch, cand)
    sources.collect(cand, {"linkedin": 5, "indeed": 2, "hellowork": 2})
    home = next(l["query"] for l in cand.config["locations"] if l["tier"] == 1)  # "Lyon, France"
    near = sorted((site, term) for site, term, loc, _ in calls if loc == home)  # boards run side by side
    assert near == [("hellowork", "marketing digital"), ("indeed", "marketing digital"),
                     ("linkedin", "marketing digital")]
    assert {h for site, _, _, h in calls if site == "linkedin"} == {5}  # each board keeps its own window


def test_a_block_lasts_one_run(monkeypatch, cand):
    sources.WATCH.blocked.add("linkedin")  # left over from an earlier cycle of the loop
    calls = _stub(monkeypatch, cand)
    sources.collect(cand, {"linkedin": 2, "indeed": 2, "hellowork": 2})
    assert any(site == "linkedin" for site, *_ in calls)


def test_board_windows_catch_up_after_a_block(cand):
    class Meta:
        def __init__(self, d):
            self.d = d

        def get(self, k):
            return self.d.get(k)

    ago = lambda h: (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat(timespec="seconds")  # noqa: E731
    w = board_windows(Meta({"last_ok_linkedin": ago(7.5), "last_ok_indeed": ago(0.5)}), cand.config, 2)
    assert w == {"linkedin": 8, "indeed": 2, "hellowork": 72, "glassdoor": 72}  # never searched yet: full first window
    assert board_windows(Meta({"last_ok_linkedin": ago(500)}), cand.config, 2)["linkedin"] == 72


def test_linkedin_runs_every_few_hours_and_rests_after_a_block(cand):
    from hunter.pipeline import board_due

    class Meta:
        def __init__(self, d):
            self.d = d

        def get(self, k):
            return self.d.get(k)

    ago = lambda h: (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat(timespec="seconds")  # noqa: E731
    cand.config["scraping"]["board_every_hours"] = {"linkedin": 3}
    assert board_due(Meta({}), cand.config, "linkedin")
    assert not board_due(Meta({"last_ok_linkedin": ago(1)}), cand.config, "linkedin")
    assert board_due(Meta({"last_ok_linkedin": ago(3)}), cand.config, "linkedin")
    assert not board_due(Meta({"last_ok_linkedin": ago(5), "blocked_linkedin": ago(1)}), cand.config, "linkedin")
    assert board_due(Meta({"last_ok_indeed": ago(0.5)}), cand.config, "indeed")  # no pacing for the others


def test_a_resting_board_is_not_searched(monkeypatch, cand):
    calls = _stub(monkeypatch, cand)
    sources.collect(cand, {"indeed": 2, "hellowork": 2})
    assert calls and not any(site == "linkedin" for site, *_ in calls)


def test_health_ping_never_breaks_the_loop(cand, monkeypatch):
    from hunter import main

    hits = []
    monkeypatch.setattr(main.requests, "get", lambda url, timeout: hits.append(url))
    main.ping(cand)
    assert hits == []  # not configured: nothing sent
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc-ping.com/abc/")
    main.ping(cand, "/start")
    main.ping(cand, "/fail")
    assert hits == ["https://hc-ping.com/abc/start", "https://hc-ping.com/abc/fail"]

    def down(url, timeout):
        raise main.requests.ConnectionError("offline")
    monkeypatch.setattr(main.requests, "get", down)
    main.ping(cand)  # offline: logged, no exception


def test_titles_from_double_escaped_feeds_read_normally():
    j = sources.job(id="x", title="DIGITAL &amp; B2B MARKETING MANAGER H/F", company="L&#39;Occitane &amp; Co")
    assert j["title"] == "DIGITAL & B2B MARKETING MANAGER H/F" and j["company"] == "L'Occitane & Co"


def test_nothing_is_sent_at_night(cand):
    from hunter.pipeline import sending_hours

    at = lambda h: datetime(2026, 11, 2, h, 30)  # noqa: E731
    assert not sending_hours(cand.config, at(2)) and not sending_hours(cand.config, at(7))
    assert sending_hours(cand.config, at(8)) and sending_hours(cand.config, at(23))


def test_a_long_pause_is_reported(cand):
    from hunter.pipeline import paused_hours
    from hunter.store import Store

    store = Store(cand)
    assert paused_hours(store) == 0  # first run ever
    store.put("last_run", (datetime.now(timezone.utc) - timedelta(hours=1.5)).isoformat(timespec="seconds"))
    assert paused_hours(store) == 0  # a normal hourly gap
    store.put("last_run", (datetime.now(timezone.utc) - timedelta(hours=19)).isoformat(timespec="seconds"))
    assert paused_hours(store) == 19


def test_a_big_catch_up_is_scored_over_several_runs(cand):
    from hunter.pipeline import cap_scoring
    from hunter.store import Store

    store = Store(cand)
    jobs = [sources.job(id=f"x:{i}", title=f"Job {i}", company="ACME", posted=f"2026-10-{10 + i:02d}") for i in range(5)]
    kept = cap_scoring(jobs, store, 2)
    assert [j["id"] for j in kept] == ["x:4", "x:3"]  # the freshest now (none in the home region)
    assert sorted(j["id"] for j in store.pending()) == ["x:0", "x:1", "x:2"]  # the rest next time
    assert cap_scoring(jobs[:2], store, 5) == jobs[:2]


def test_reposts_naming_a_job_board_as_employer_are_skipped(monkeypatch):
    import pandas as pd

    rows = [{"id": "gd-1", "title": "Chef de projet marketing", "company": "Hellowork", "job_url": "u1"},
            {"id": "gd-2", "title": "Chef de projet social media", "company": "Brainsonic", "job_url": "u2"}]
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return pd.DataFrame(rows)
    monkeypatch.setattr("jobspy.scrape_jobs", fake)
    jobs = sources.listing("glassdoor", "chef de projet", "Paris", 24, 25)
    assert [j["company"] for j in jobs] == ["Brainsonic"]
    assert seen["fetch_description"] is True and seen["site_name"] == ["glassdoor"]


def test_boards_are_searched_side_by_side(monkeypatch, cand):
    import threading

    together = threading.Barrier(4, timeout=5)  # only passes if the 4 boards are being searched at the same time
    started = set()

    def listing(site, term, location, hours, n):
        if site not in started:
            started.add(site)
            together.wait()
        return []
    monkeypatch.setattr(sources, "listing", listing)
    cand.config["scraping"]["pause_between_searches_s"] = [0, 0]
    cand.config["sources"].update(linkedin=True, indeed=True, hellowork=True, glassdoor=True)
    sources.collect(cand, {"linkedin": 2, "indeed": 2, "hellowork": 2, "glassdoor": 2})
    assert started == {"linkedin", "indeed", "hellowork", "glassdoor"} and not together.broken


def test_the_loop_restarts_itself_when_its_code_changes(tmp_path, monkeypatch):
    import time as _time

    from hunter import main

    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / "hunter").mkdir()
    code = tmp_path / "hunter" / "pipeline.py"
    code.write_text("x = 1")
    started = _time.time() + 1
    assert not main.code_changed(started)
    import os
    os.utime(code, (started + 5, started + 5))
    assert main.code_changed(started) and main.RESTART == 3
    assert main.code_errors() == ""
    code.write_text('print(f"half-finished\n")')  # an edit caught mid-way must never restart into a crash
    assert main.code_errors().startswith("pipeline.py line 1:")



def test_home_region_postings_are_scored_first(cand):
    from hunter.pipeline import cap_scoring
    from hunter.store import Store

    store = Store(cand)
    far = sources.job(id="x:far", title="Chef de projet", company="A", location="Saint Denis, 97400, La Réunion",
                      posted="2026-10-31")
    paris = sources.job(id="x:paris", title="Chef de projet", company="B", location="Paris 09 - 75", posted="2026-10-20")
    remote = sources.job(id="x:remote", title="Chef de projet", company="C", location="Télétravail, France",
                         posted="2026-10-25")
    home = {"75", "77", "78", "91", "92", "93", "94", "95"}  # a Paris-based candidate
    assert [j["id"] for j in cap_scoring([far, paris, remote], store, 2, home)] == ["x:remote", "x:paris"]

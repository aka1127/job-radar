"""The archive is shared by the loop and the background crawler, each with its own connection, sometimes by a second
process: a database that stays busy must never stop a candidate's cycle (the archive is a side record)."""
import logging
import sqlite3

import pytest

from hunter import archive, pipeline, sources
from hunter.store import Store


def posting(i: int) -> dict:
    return sources.job(id=f"indeed:{i}", site="indeed", title=f"Product Designer {i}", company="ACME",
                       location="Lyon", description="Missions " * 40)


def offline_run(monkeypatch, postings: list[dict]):
    """run() with the network and Claude faked: the boards return `postings`, every score is low (nothing to ship).
    Returns the ids scored and what the career-page poll's keep() answered."""
    scored, kept = [], []

    class FakeClaude:
        def __init__(self, cand):
            pass

        def triage(self, jobs):
            return ["possible"] * len(jobs)

        def score(self, job):
            scored.append(job["id"])
            return {"score": 20, "language": "en", "location_type": "home_region", "dealbreakers": [],
                    "contract": "permanent", "family": "product_design"}

    def poll(store, cfg, title_ok, keep=None, **kw):
        crawled = [sources.job(id="lever:kerno:1", site="career page (lever)", title="Designer", company="Kerno",
                               location="Nantes", description="Missions " * 40)]
        kept.append(keep(crawled) if keep else None)
        return []
    monkeypatch.setattr(pipeline, "Claude", FakeClaude)
    monkeypatch.setattr(pipeline.sources, "collect", lambda cand, windows: list(postings))
    monkeypatch.setattr(pipeline.careers, "poll", poll)
    monkeypatch.setattr(pipeline, "grow_watchlist", lambda *a: None)
    monkeypatch.setattr(pipeline, "discover", lambda *a: None)
    monkeypatch.setattr(pipeline.harvest, "harvest_due", lambda *a, **k: 0)
    return scored, kept


def hold_write_lock(path) -> sqlite3.Connection:
    """A second connection that holds the database's write lock until it is closed."""
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("begin immediate")
    return other


def test_a_locked_archive_never_stops_a_run(cand, telegram, monkeypatch, tmp_path, caplog):
    """Another connection holds the write lock for the whole cycle (the crawler mid-write, or a run that hung): the
    archive saves are skipped with a warning, the postings are still scored and saved, and the cycle ends normally."""
    monkeypatch.setattr(archive, "TIMEOUT", 0.2)  # a short wait keeps the test quick
    archive.Archive()  # creates the database in WAL mode (the cand fixture points DB into tmp_path)
    other = hold_write_lock(tmp_path / "jobs.db")
    scored, kept = offline_run(monkeypatch, [posting(1)])
    try:
        with caplog.at_level(logging.WARNING, logger="hunter"):
            pipeline.run(cand)
    finally:
        other.close()
    assert scored == ["indeed:1"] and kept == [0]  # scored anyway; the poll's keep() answered 0 instead of raising
    assert "archive save skipped" in caplog.text
    store = Store(cand)
    assert tuple(store.db.execute("select status, score from jobs where id='indeed:1'").fetchone()) == ("skipped", 20)
    assert store.get("last_run")  # the cycle ran to its end
    assert sqlite3.connect(tmp_path / "jobs.db").execute("select count(*) from postings").fetchone()[0] == 0


def test_a_run_goes_on_when_the_archive_cannot_be_opened(cand, telegram, monkeypatch, caplog):
    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(pipeline.archive, "Archive", locked)
    scored, kept = offline_run(monkeypatch, [posting(2)])
    with caplog.at_level(logging.WARNING, logger="hunter"):
        pipeline.run(cand)
    assert scored == ["indeed:2"] and kept == [None]  # no archive this run, so the poll gets no keep()
    assert "archive unavailable" in caplog.text


def test_a_busy_database_raises_after_a_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "TIMEOUT", 0.2)
    arch = archive.Archive(tmp_path / "jobs.db")
    assert arch.db.execute("pragma journal_mode").fetchone()[0] == "wal"
    other = hold_write_lock(tmp_path / "jobs.db")
    try:
        with pytest.raises(sqlite3.OperationalError):
            arch.save([posting(1)])
        assert not arch.db.in_transaction  # rolled back: nothing half-written, the next save starts clean
    finally:
        other.close()
    assert arch.save([posting(1)]) == 1  # the lock is gone: the same batch goes in


def test_lookups_commit_at_once_and_stop_after_their_time(tmp_path, monkeypatch):
    arch = archive.Archive(tmp_path / "jobs.db")
    asked = []

    class R:
        def json(self):
            return [{"codeDepartement": "69"}]
    monkeypatch.setattr(archive.requests, "get", lambda url, params, timeout: asked.append(params) or R())
    assert arch.lookup("Vénissieux, France") == "69"
    assert not arch.db.in_transaction  # committed at once: the write lock is not held through the next lookups
    towns = [sources.job(id=f"x:{i}", site="linkedin", title="T", company="A", location=f"Ville{i}, France")
             for i in range(3)]
    assert arch.save(towns, lookup_seconds=0) == 3 and len(asked) == 1  # out of time: saved without lookups
    assert arch.save([sources.job(id="x:9", site="linkedin", title="T", company="A", location="Ville9, France")]) == 1
    assert len(asked) == 2

from hunter import sources


class FakeClaude:
    """Sorts by title like the triage call would, and counts the calls."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def triage(self, jobs):
        self.calls.append([j["id"] for j in jobs])
        if self.fail:
            raise RuntimeError("claude triage failed 3 times")
        return ["skip" if "IT" in j["title"] else "core" if "sport" in j["title"] else "possible" for j in jobs]


def jobs():
    return [sources.job(id="x:it", title="Chef de projet IT", company="A", location="Paris"),
            sources.job(id="x:sport", title="Chef de projet marketing sport", company="B", location="Marseille",
                        posted="2026-10-01"),
            sources.job(id="x:mkt", title="Chef de projet marketing", company="C", location="Paris 09 - 75",
                        posted="2026-10-31")]


def test_triage_drops_clear_misfits_and_core_targets_are_scored_first(cand):
    from hunter.pipeline import cap_scoring, triage
    from hunter.store import Store

    store, claude = Store(cand), FakeClaude()
    kept = triage(claude, jobs(), store, batch=2)
    assert [j["id"] for j in kept] == ["x:sport", "x:mkt"]
    assert claude.calls == [["x:it", "x:sport"], ["x:mkt"]]  # batches of 2
    row = store.db.execute("select status, data from jobs where id='x:it'").fetchone()
    assert row["status"] == "skipped" and '"triage": "skip"' in row["data"]
    # the core target goes first even though it is older and outside the home region
    assert [j["id"] for j in cap_scoring(kept, store, 1)] == ["x:sport"]
    assert [j["id"] for j in store.pending()] == ["x:mkt"]


def test_a_sorted_posting_is_not_sent_to_triage_again(cand):
    from hunter.pipeline import triage
    from hunter.store import Store

    store, claude = Store(cand), FakeClaude()
    first = triage(claude, jobs(), store)
    later = triage(claude, first, store)  # e.g. postings that waited for the next run
    assert len(claude.calls) == 1 and [j["id"] for j in later] == ["x:sport", "x:mkt"]


def test_when_triage_fails_every_posting_goes_on_to_the_full_scoring(cand):
    from hunter.pipeline import triage
    from hunter.store import Store

    kept = triage(FakeClaude(fail=True), jobs(), Store(cand))
    assert [j["id"] for j in kept] == ["x:it", "x:sport", "x:mkt"] and not any(j.get("triage") for j in kept)


def test_the_triage_answer_is_read_by_number(cand, monkeypatch):
    from hunter.llm import Claude

    claude = Claude(cand)
    seen = {}

    def run(step, prompt, schema=None, tools=()):
        seen["step"], seen["prompt"] = step, prompt
        return {"items": [{"n": 2, "verdict": "skip"}, {"n": 1, "verdict": "core"}]}  # out of order, one missing
    monkeypatch.setattr(claude.cc, "run", run)
    assert claude.triage(jobs()) == ["core", "skip", "possible"]
    assert seen["step"] == "triage" and "1. Chef de projet IT | A | Paris" in seen["prompt"]

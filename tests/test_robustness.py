"""Any country, any machine: local and English city names both reach the home area, remote words in every CV
language, country names people actually type, the French archive rules off outside France, alert emails placed in
the candidate's country, and the small repairs that keep a hand-written config or a bad command from crashing."""
from pathlib import Path

import pytest

from hunter import alerts, archive, careers, geo, targets
from hunter.candidate import tidy
from hunter.text import fold


def test_local_and_english_city_names_both_reach_the_home_area():
    for home in ("Munich", "München"):
        near = targets.near_home({"country": "DE", "home": home, "home_radius_km": 30})
        assert near("München") and near("Munich, Germany") and near("Garching bei München") and not near("Berlin")
    assert targets.near_home({"country": "PT", "home": "Lisboa", "home_radius_km": 20})("Lisbon, Portugal")
    assert targets.near_home({"country": "DE", "home": "Köln", "home_radius_km": 20})("Cologne")
    assert geo.home_known("München", "DE") and geo.home_known("Lyon", "FR")
    assert not geo.home_known("Unterföhring", "DE")  # under 15,000 people: GeoNames does not list it
    assert geo.home_area("Unterföhring", "DE", 30) == frozenset({"unterfohring"})  # the name alone, as documented


def test_remote_is_understood_in_every_cv_language():
    nowhere = frozenset()
    for loc in ("Remote", "Télétravail", "Homeoffice", "Home Office", "Teletrabajo", "100% remoto", "Thuiswerken",
                "Smart working", "Trabalho remoto"):
        assert geo.near(loc, nowhere), loc
    assert not geo.near("Paris", nowhere)


def test_country_names_people_type_are_understood():
    assert [geo.country_code(x) for x in ("Czech Republic", "Korea", "Côte d'Ivoire", "North Macedonia", "Allemagne")] == \
        ["CZ", "KR", "CI", "MK", "DE"]
    assert geo.country_language("LU") in ("fr", "de") and geo.country_language("MA") == "fr"  # not lb or ar: unsupported
    assert geo.country_language("DE") == "de" and geo.country_language("US") == "en"


def test_folding_keeps_letters_nfkd_would_drop():
    assert fold("København") == " kobenhavn " and fold("Łódź") == " lodz " and fold("Straße") == " strasse "
    assert fold("Æblerød") == " aeblerod "


def test_remote_postings_stay_at_the_career_page_stage(monkeypatch):
    monkeypatch.setattr(careers, "COUNTRY", "DE")
    assert careers.in_area("Remote") and careers.in_area("Remote (EU)") and careers.in_area("Berlin, Germany")
    assert not careers.in_area("Remote - US") and not careers.in_area("Paris, France")


def test_the_french_departement_rules_stay_off_outside_france(tmp_path):
    job = {"id": "x:1", "site": "linkedin", "title": "Konstrukteur", "company": "Acme", "location": "Berlin, 10115",
           "url": "https://x", "description": "d"}
    french = archive.Archive(tmp_path / "fr.db")
    assert french.save([job]) == 1 and french.db.execute("select department from postings").fetchone()[0] == "10"
    abroad = archive.Archive(tmp_path / "de.db", french=False)
    assert abroad.save([job]) == 1 and abroad.db.execute("select department from postings").fetchone()[0] == ""


def test_indeed_alerts_keep_their_country_site_and_default_to_the_candidates_country():
    assert alerts.job_link("https://de.indeed.com/rc/clk/dl?jk=0123456789abcdef&from=ja") == \
        ("indeed", "https://de.indeed.com/viewjob?jk=0123456789abcdef")
    assert alerts.job_link("https://www.indeed.com/viewjob?jk=0123456789abcdef") == \
        ("indeed", "https://www.indeed.com/viewjob?jk=0123456789abcdef")
    url = "https://de.indeed.com/viewjob?jk=0123456789abcdef"
    j = alerts.from_block("indeed", url, "Konstrukteur (m/w/d)", ["Konstrukteur (m/w/d)", "Acme GmbH", "München",
                                                                  "Vollzeit"], "2026-10-31", "DE")
    assert (j["company"], j["location"]) == ("Acme GmbH", "München")
    j = alerts.from_block("indeed", url, "Konstrukteur (m/w/d)", ["Konstrukteur (m/w/d)", "Acme GmbH"], "2026-10-31", "DE")
    assert j["location"] == "Germany"  # nothing better in the block: the alerts are set up for that country


def test_score_bars_written_as_strings_still_work():
    cfg = tidy({"min_score": {"1": "55", "2": 65}, "priority": {"min_score": {"1": 45}}})
    assert cfg["min_score"] == {1: 55, 2: 65} and cfg["priority"]["min_score"] == {1: 45}
    assert targets.bar_for({"family": "x"}, cfg)[1] == 55


def test_onboarding_refuses_what_would_break_later(tmp_path):
    from hunter import onboard

    with pytest.raises(SystemExit, match="CV not found"):
        onboard.cv_text(tmp_path / "missing.pdf")
    (tmp_path / "cv.doc").write_bytes(b"\xd0\xcf\x11\xe0" + b"x" * 400)
    with pytest.raises(SystemExit, match=r"\.docx"):
        onboard.cv_text(tmp_path / "cv.doc")
    cv = tmp_path / "cv.txt"
    cv.write_text("Alex Moreau, designer. " * 20, encoding="utf-8")
    with pytest.raises(SystemExit, match="reserved"):
        onboard.onboard("jobs", cv, None, root=tmp_path / "candidates")
    leak = onboard.conditions_leak({"other_facts": ["Salary expectation 62,000 EUR per year"]}, {"salary": "62000 EUR"})
    assert leak and "salary" in leak[0]
    assert onboard.conditions_leak({"other_facts": ["Driving licence B"]}, {"salary": "62000 EUR"}) == []
    assert "min_score must look like" in "; ".join(onboard.check_config({"min_score": {"tier1": 55}}))


def test_data_can_live_outside_the_checkout(tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("HUNTER_HOME", str(tmp_path))
    import hunter.candidate as candidate

    reloaded = importlib.reload(candidate)
    try:
        assert reloaded.HOME == tmp_path.resolve() and reloaded.CANDIDATES == tmp_path.resolve() / "candidates"
        assert reloaded.EXAMPLE == reloaded.ROOT / "candidates" / "example"  # the example stays with the engine
        assert reloaded.available() == []
        with pytest.raises(SystemExit, match="onboard"):
            reloaded.Candidate()
    finally:
        monkeypatch.delenv("HUNTER_HOME")
        importlib.reload(candidate)

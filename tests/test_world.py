"""Any country, any language: places, home areas, contracts, CV languages and prompts come from the candidate's
config. The example candidate is moved to Germany here to prove nothing is French by default."""
import pytest

from hunter import ats, careers, geo, i18n, sources, targets
from hunter.render import Renderer


@pytest.mark.parametrize("location, country, expected", [
    ("Berlin, Germany", "DE", True), ("München", "DE", True), ("Paris, France", "DE", False),
    ("Austin, TX", "US", True), ("Paris, Texas", "US", True), ("Paris, Texas", "FR", False),
    ("Lisbon (PT)", "PT", True), ("Toronto, ON, Canada", "CA", True), ("Remote", "DE", False),
    ("Casablanca", "MA", True), ("Saint-Denis de la Réunion", "DE", False),
])
def test_a_job_is_placed_in_its_country(location, country, expected):
    assert geo.in_country(location, country) is expected


def test_the_home_area_is_the_cities_within_reach():
    area = geo.home_area("Lyon", "FR", 40)
    assert geo.near("Villeurbanne", area) and geo.near("Télétravail", area) and not geo.near("Paris 09", area)
    near = targets.near_home({"country": "DE", "home": "Berlin", "home_radius_km": 30})
    assert near("Potsdam, Brandenburg") and not near("Hamburg")


def test_countries_are_understood_in_any_spelling():
    assert [geo.country_code(x) for x in ("Germany", "deutschland", "de", "UK", "Atlantis")] == ["DE", "DE", "DE", "GB", None]
    assert geo.country_language("DE") == "de" and geo.country_language("BR") == "pt"


def test_cv_languages_follow_the_country_unless_the_config_says():
    assert targets.cv_languages({"country": "DE"}) == ["en", "de"]
    assert targets.cv_languages({"country": "FR", "cv_languages": ["fr", "en"]}) == ["fr", "en"]
    assert targets.cv_languages({"country": "MA"}) == ["en", "fr"]  # no Arabic CVs yet: French, the next language there
    assert i18n.output_language("de", ["en", "de"]) == "de" and i18n.output_language("ja", ["fr", "de"]) == "fr"


def test_posting_languages_are_detected():
    de = ("Wir suchen eine erfahrene Person für unser Team in Berlin. Sie arbeiten mit der Produktentwicklung und "
          "den Kunden zusammen und sind für die Planung der Projekte verantwortlich, mit einem Fokus auf die Qualität "
          "und die Zusammenarbeit im Team und mit den Partnern.")
    es = ("Buscamos una persona para nuestro equipo en Madrid. Trabajarás con el equipo de producto y los clientes "
          "para la planificación de los proyectos, con una gran autonomía y en un entorno internacional que está "
          "en pleno crecimiento y con las mejores condiciones.")
    assert i18n.detect(de) == "de" and i18n.detect(es) == "es" and i18n.detect("Data Analyst") is None


def test_contracts_are_named_the_local_way():
    assert targets.contract("CDI") == "permanent" and targets.contract("fixed-term") == "unknown"
    assert targets.contract_label("permanent", {"country": "FR"}) == "CDI"
    assert targets.contract_label("permanent", {"country": "DE"}) == "Permanent"
    assert targets.contract_ok("CDD", {"contracts": ["permanent", "fixed_term"]})
    assert not targets.contract_ok("internship_or_apprenticeship", {"contracts": ["permanent"]})


def test_boards_run_only_where_they_exist():
    assert sources.board_works("hellowork", "FR") and not sources.board_works("hellowork", "DE")
    assert sources.board_works("indeed", "DE") and sources.jobspy_country("US") == "usa"
    assert not sources.board_works("glassdoor", "DZ") and sources.board_works("linkedin", "DZ")


def test_career_boards_keep_the_jobs_of_the_candidates_country(monkeypatch):
    monkeypatch.setattr(careers, "COUNTRY", "DE")
    assert careers.in_area("Berlin") and not careers.in_area("Paris") and careers.in_area("", empty=True)


def test_the_scorer_is_told_the_candidates_country_and_contracts(cand):
    from hunter.llm import Claude, score_schema

    cand.config.update(country="DE", home="Berlin")
    seen = {}
    claude = Claude(cand)
    claude.cc.run = lambda step, prompt, schema=None, tools=(): seen.update(prompt=prompt, schema=schema) or {}
    claude.score({"title": "Data Analyst", "company": "A", "location": "Berlin", "site": "x", "description": "x"})
    assert "open to people in Germany" in seen["prompt"] and "unbefristet" in seen["prompt"]
    assert seen["schema"]["properties"]["contract"]["enum"][0] == "permanent"
    assert score_schema(cand.config)["properties"]["location_type"]["enum"][1] == "remote_country"


@pytest.fixture(scope="module")
def renderer():
    with Renderer() as r:
        yield r


def test_a_german_cv_reads_like_a_german_one(renderer, cand, cv_en, tmp_path):
    cv = cv_en | {"lang": "de"}  # the profile has no German texts: English content, German frame
    pdf = tmp_path / "cv.pdf"
    pages, _ = renderer.cv_pdf(cv, cand, pdf)
    res = ats.check(pdf, [], cv["headline"].split(" | ")[0], "de", cand, max_pages=2, ids=[x["id"] for x in cv["experience"]])
    assert res["sections_ok"] and "BERUFSERFAHRUNG" in res["text"] and "KERNKOMPETENZEN" in res["text"]
    assert "Sept. 2021 - Jan. 2024" in res["text"] and not [i for i in res["issues"] if "parse" in i], res["issues"]
    letter = tmp_path / "letter.pdf"
    renderer.letter_pdf("Sehr geehrte Damen und Herren,\n\nText.\n\nMit freundlichen Grüßen", {"title": "Analyst",
                        "company": "A"}, "Analyst", cand, "de", letter)
    first_line = ats.pdf_text(letter)[0]
    assert "Lyon, " in first_line and any(m in first_line for m in i18n.LONG_MONTHS["de"].split())

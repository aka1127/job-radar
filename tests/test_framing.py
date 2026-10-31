"""One profile, several job families: the CV is angled per family, and jobs in the candidate's priority sector
(the example candidate: sport) stand out. Families, priority and angles all come from the candidate's config."""
import pytest

from conftest import telegram_html_errors
from hunter import ats, notify
from hunter.render import Renderer, assemble, banner_html, plain_text
from hunter.targets import bar_for, framing, is_priority, priority_first


@pytest.fixture(scope="module")
def renderer():
    with Renderer() as r:
        yield r


def sport_cv(cv_fr):
    exp = [{"id": "courtside", "alt_title": False, "bullets": [
        "Création de **Courtside, média basket indépendant** : 1,1 M de vues Instagram en 30 jours.",
        "Animation de **Courtside Talks**, podcast d'entretiens avec joueurs, coachs et un directeur général de club.",
        "Création de **Pickup Diaries**, série vidéo hebdomadaire tournée sur les terrains de Lyon."]}]
    keep = {"velora": 2, "portside": 2, "bocado": 1, "atlantica": 2, "pixelfox": 1, "callwave": 1}  # budget with projects
    exp += [x | {"bullets": x["bullets"][:keep[x["id"]]]} for x in cv_fr["experience"]]
    return cv_fr | {"framing": "sport", "experience": exp, "skills": cv_fr["skills"][:4],
                    "headline": "Chef de projet marketing sport | Média basket, digital, partenariats"}


def test_family_picks_the_angle(cand):
    cfg = cand.config
    assert framing({"family": "event"}, cfg) == "event"
    assert framing({"family": "digital_marketing", "priority_sector": True}, cfg) == "sport"  # marketing at a club
    assert framing({"family": "other"}, cfg) == "digital_marketing" and framing({}, cfg) == "digital_marketing"
    assert is_priority({"family": "sport"}, cfg) and not is_priority({"family": "partnerships"}, cfg)
    assert framing({"family": "sport"}, {}) == "default" and not is_priority({"family": "sport"}, {})  # no config


def test_sport_cv_shows_the_creative_work_on_one_page(renderer, cand, cv_fr, tmp_path):
    cv = sport_cv(cv_fr)
    c, _ = assemble(cv, cand)
    assert [x["name"] for x in c["projects"]][0] == "Courtside Shots" and c["portfolio"]
    assert "1,1 M" in c["highlights"][0]["html"]
    assert any("basket professionnel" in e["detail"] for e in c["education"])
    pdf = tmp_path / "cv.pdf"
    pages, scale = renderer.cv_pdf(cv, cand, pdf)
    res = ats.check(pdf, [], "Chef de projet marketing sport", "fr", cand, ids=[x["id"] for x in cv["experience"]])
    assert pages == 1 and scale >= 0.86, (pages, scale)
    assert res["sections_ok"] and "courtside.example.com" in res["text"] and "PROJETS & ENGAGEMENTS" in res["text"]
    assert not [i for i in res["issues"] if "parse" in i or "pages" in i], res["issues"]
    assert ats.truth_flags(plain_text(cv, cand), cand) == []


def test_marketing_cv_stays_plain(cand, cv_fr):
    c, _ = assemble(cv_fr | {"framing": "digital_marketing"}, cand)
    assert c["projects"] == [] and not c["portfolio"] and "+5 ans" in c["highlights"][0]["html"]
    assert all(not e["detail"].startswith("Mémoire") for e in c["education"])


def test_project_roles_can_use_the_project_manager_title(renderer, cand, cv_en, tmp_path):
    exp = [x | {"alt_title": x["id"] == "portside"} for x in cv_en["experience"]]
    cv = cv_en | {"framing": "project_management", "experience": exp}
    c, _ = assemble(cv, cand)
    assert next(j for j in c["experience"] if j["company"] == "Portside Logistics")["title"] == \
        "Project Manager, Digital Strategy"
    assert c["projects"][0]["name"] == "Lyon Student Sports Association"
    assert not any("Lyon Student Sports Association" in a for a in c["achievements"])  # told once, in projects
    pdf = tmp_path / "cv.pdf"
    renderer.cv_pdf(cv, cand, pdf)
    res = ats.check(pdf, [], cv["headline"].split(" | ")[0], "en", cand, ids=[x["id"] for x in exp])
    assert "some job titles, companies or dates did not parse" not in res["issues"]


def test_priority_jobs_stand_out_in_telegram(cand, tmp_path):
    job = {"id": "linkedin:1", "site": "linkedin", "title": "Chef de projet digital (H/F)", "company": "ASVEL",
           "location": "Villeurbanne", "posted": "", "url": "https://example.com", "apply_url": "", "description": "x"}
    fit = {"score": 72, "why_fit": ["basketball media"], "gaps": [], "contract": "CDI", "family": "sport",
           "priority_sector": True}
    page = banner_html(job, fit, None, cand.config)
    assert 'class="banner priority"' in page and "SPORT · PRIORITY" in page
    plain = banner_html(job, fit | {"family": "digital_marketing", "priority_sector": False}, None, cand.config)
    assert "banner priority" not in plain and "NEW JOB" in plain
    assert "PRIORITY" not in banner_html(job, fit, None)  # without a priority in the config, no special look
    r = {"tier": 1, "lang": "fr", "ats": {"score": 90}, "screen": {"score": 80}, "flags": [],
         "pack": {"hiring_manager_titles": ["Head of Digital"]}}
    card = notify.card(job, fit, r, cand.config)
    assert card.splitlines()[0] == "🏀🟠 <b>SPORTS INDUSTRY · PRIORITY</b>" and telegram_html_errors(card) == []
    assert "PRIORITY" not in notify.card(job, fit | {"family": "event", "priority_sector": False}, r, cand.config)
    assert "(outside Lyon)" in notify.card(job, fit, r | {"tier": 2}, cand.config)


def test_priority_never_promotes_a_weak_match(cand):
    cfg = cand.config
    sales_at_club = {"family": "partnerships", "priority_sector": True, "score": 48}
    club_role = {"family": "sport", "priority_sector": True, "score": 50}
    assert bar_for(sales_at_club, cfg) == cfg["min_score"]  # normal bar: 48 is out
    assert bar_for(club_role, cfg) == cfg["priority"]["min_score"]  # a real sport job keeps the lower bar
    assert not priority_first(sales_at_club, 1, cfg) and not priority_first(club_role, 1, cfg)
    assert priority_first({"family": "sport", "score": 70}, 1, cfg)
    assert priority_first({"family": "content_social", "priority_sector": True, "score": 76}, 1, cfg)

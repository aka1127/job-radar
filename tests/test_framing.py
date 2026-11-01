"""One profile, several job families: the CV is angled per family, and jobs in the candidate's priority sector
(the example candidate: healthcare) stand out. Families, priority and angles all come from the candidate's config."""
import pytest

from conftest import telegram_html_errors
from hunter import ats, notify
from hunter.render import Renderer, assemble, banner_html, plain_text
from hunter.targets import bar_for, framing, is_priority, priority_first


@pytest.fixture(scope="module")
def renderer():
    with Renderer() as r:
        yield r


def health_cv(cv_fr):
    exp = [{"id": "hexalab", "alt_title": False, "bullets": [
        "Conception du **portail patient et de l'application soignants**, de la recherche au handoff développeurs.",
        "Animation de **plus de 120 tests utilisateurs** avec des patients, des infirmiers et des médecins.",
        "Mise en conformité de **3 produits WCAG 2.1 AA** (RGAA) avec l'équipe front.",
        "Création de **Pulse, le design system** utilisé par 4 équipes produit."]}]
    keep = {"orbital": 2, "kerno": 2, "atelier": 1}  # budget with projects
    exp += [x | {"bullets": x["bullets"][:keep[x["id"]]]} for x in cv_fr["experience"] if x["id"] in keep]
    return cv_fr | {"framing": "health", "experience": exp, "skills": cv_fr["skills"][:4],
                    "headline": "Product Designer santé | Portail patient, design system, accessibilité"}


def test_family_picks_the_angle(cand):
    cfg = cand.config
    assert framing({"family": "accessibility"}, cfg) == "accessibility"
    assert framing({"family": "product_design", "priority_sector": True}, cfg) == "health"  # a designer at a hospital group
    assert framing({"family": "other"}, cfg) == "product_design" and framing({}, cfg) == "product_design"
    assert is_priority({"family": "health"}, cfg) and not is_priority({"family": "design_system"}, cfg)
    assert framing({"family": "health"}, {}) == "default" and not is_priority({"family": "health"}, {})  # no config


def test_health_cv_shows_the_portfolio_work_on_one_page(renderer, cand, cv_fr, tmp_path):
    cv = health_cv(cv_fr)
    c, _ = assemble(cv, cand)
    assert [x["name"] for x in c["projects"]] == ["Pro bono design"] and c["portfolio"]
    assert "120+" in c["highlights"][0]["html"]
    assert any("hôpital" in e["detail"] for e in c["education"])
    pdf = tmp_path / "cv.pdf"
    pages, scale = renderer.cv_pdf(cv, cand, pdf)
    res = ats.check(pdf, [], "Product Designer santé", "fr", cand, ids=[x["id"] for x in cv["experience"]])
    assert pages == 1 and scale >= 0.86, (pages, scale)
    assert res["sections_ok"] and "alexmoreau.example.com" in res["text"] and "PROJETS & ENGAGEMENTS" in res["text"]
    assert not [i for i in res["issues"] if "parse" in i or "pages" in i], res["issues"]
    assert ats.truth_flags(plain_text(cv, cand), cand) == []


def test_accessibility_cv_stays_plain(cand, cv_fr):
    c, _ = assemble(cv_fr | {"framing": "accessibility"}, cand)
    assert c["projects"] == [] and not c["portfolio"] and "+8 ans" in c["highlights"][0]["html"]
    assert all(not e["detail"].startswith("Projet de diplôme") for e in c["education"])
    assert "RGAA 4 auditor training" in c["certifications"]  # certifications_extra for that family only


def test_research_roles_can_use_the_alternative_title(renderer, cand, cv_en, tmp_path):
    exp = [x | {"alt_title": x["id"] == "orbital"} for x in cv_en["experience"]]
    cv = cv_en | {"framing": "ux_research", "experience": exp}
    c, _ = assemble(cv, cand)
    assert next(j for j in c["experience"] if j["company"] == "Orbital Studio")["title"] == "UX Researcher & Designer"
    assert c["projects"][0]["name"] == "Lyon UX Meetup"
    assert not any("Lyon UX Meetup" in a for a in c["achievements"])  # told once, in projects
    pdf = tmp_path / "cv.pdf"
    renderer.cv_pdf(cv, cand, pdf)
    res = ats.check(pdf, [], cv["headline"].split(" | ")[0], "en", cand, ids=[x["id"] for x in exp])
    assert "some job titles, companies or dates did not parse" not in res["issues"]


def test_priority_jobs_stand_out_in_telegram(cand, tmp_path):
    job = {"id": "linkedin:1", "site": "linkedin", "title": "UX Designer (H/F)", "company": "Northwind Santé",
           "location": "Villeurbanne", "posted": "", "url": "https://example.com", "apply_url": "", "description": "x"}
    fit = {"score": 72, "why_fit": ["patient products"], "gaps": [], "contract": "CDI", "family": "health",
           "priority_sector": True}
    page = banner_html(job, fit, None, cand.config)
    assert 'class="banner priority"' in page and "HEALTH · PRIORITY" in page and "<svg" in page
    plain = banner_html(job, fit | {"family": "product_design", "priority_sector": False}, None, cand.config)
    assert "banner priority" not in plain and "NEW JOB" in plain
    assert "PRIORITY" not in banner_html(job, fit, None)  # without a priority in the config, no special look
    r = {"tier": 1, "lang": "fr", "ats": {"score": 90}, "screen": {"score": 80}, "flags": [],
         "pack": {"hiring_manager_titles": ["Head of Design"]}}
    card = notify.card(job, fit, r, cand.config)
    assert card.splitlines()[0] == "🩺 <b>HEALTHCARE · PRIORITY</b>" and telegram_html_errors(card) == []
    assert "PRIORITY" not in notify.card(job, fit | {"family": "accessibility", "priority_sector": False}, r, cand.config)
    assert "(outside Lyon)" in notify.card(job, fit, r | {"tier": 2}, cand.config)


def test_priority_never_promotes_a_weak_match(cand):
    cfg = cand.config
    system_at_hospital = {"family": "design_system", "priority_sector": True, "score": 48}
    health_role = {"family": "health", "priority_sector": True, "score": 50}
    assert bar_for(system_at_hospital, cfg) == cfg["min_score"]  # normal bar: 48 is out
    assert bar_for(health_role, cfg) == cfg["priority"]["min_score"]  # a real health job keeps the lower bar
    assert not priority_first(system_at_hospital, 1, cfg) and not priority_first(health_role, 1, cfg)
    assert priority_first({"family": "health", "score": 70}, 1, cfg)
    assert priority_first({"family": "ux_research", "priority_sector": True, "score": 76}, 1, cfg)

"""The PDFs: one designed page and a parse-safe plain version, read back the way an ATS reads them."""
import re

import pytest

from hunter import ats
from hunter.render import Renderer, plain_text
from hunter.text import local_dates


@pytest.fixture(scope="module")
def renderer():
    with Renderer() as r:
        yield r


@pytest.mark.parametrize("which", ["cv_en", "cv_fr"])
def test_designed_cv_is_one_clean_page(renderer, cand, which, request, tmp_path):
    cv = request.getfixturevalue(which)
    pdf = tmp_path / "cv.pdf"
    pages, scale = renderer.cv_pdf(cv, cand, pdf)
    res = ats.check(pdf, [], cv["headline"].split(" | ")[0], cv["lang"], cand, ids=[x["id"] for x in cv["experience"]])
    assert pages == 1 and scale >= 0.86
    assert res["sections_ok"] and res["issues"] == [], res["issues"]
    assert res["score"] >= 95


@pytest.mark.parametrize("which", ["cv_en", "cv_fr"])
def test_plain_cv_follows_the_parse_safe_layout(renderer, cand, which, request, tmp_path):
    cv = request.getfixturevalue(which)
    pdf = tmp_path / "plain.pdf"
    pages, scale = renderer.cv_pdf(cv, cand, pdf, plain=True)
    ids = [x["id"] for x in cv["experience"]]
    res = ats.check(pdf, [], cv["headline"].split(" | ")[0], cv["lang"], cand, max_pages=2, ids=ids)
    assert pages <= 2 and res["issues"] == [], res["issues"]
    lines, i = [l.strip() for l in res["text"].splitlines()], 0
    for e in (e for e in cand.profile["experience"] if e["id"] in ids):  # in CV order; titles can repeat
        title = re.sub(r"\s*\([^()]*\)\s*$", "", e[f"title_{cv['lang']}"])
        i = lines.index(title, i)  # the title alone on its line, no "(alternance)" glued to it
        assert lines[i + 1] == e["company"] and lines[i + 2] == local_dates(e, cv["lang"])
        i += 3


def test_reading_order_is_top_to_bottom(renderer, cand, cv_en, tmp_path):
    pdf = tmp_path / "cv.pdf"
    renderer.cv_pdf(cv_en, cand, pdf)
    text = ats.pdf_text(pdf)[0]
    start = text.lower().index("professional experience")  # strengths above also name employers
    shown = {x["id"] for x in cv_en["experience"]}
    order = [text.index(e["company"], start) for e in cand.profile["experience"] if e["id"] in shown]
    assert text.index(cand.profile["identity"]["name"].split()[1]) < start and order == sorted(order)


def test_letter_is_one_page(renderer, cand, tmp_path):
    letter = "Madame, Monsieur,\n\n" + ("Paragraphe de motivation. " * 25 + "\n\n") * 3 + "Bien cordialement,"
    pages, _ = renderer.letter_pdf(letter, {"title": "Chargé CRM (H/F)", "company": "SRA"}, "CRM", cand, "fr",
                                   tmp_path / "l.pdf", "#12355b")
    assert pages == 1
    assert "(H/F)" not in ats.pdf_text(tmp_path / "l.pdf")[0]


def test_telegram_header_picture(renderer, tmp_path):
    from PIL import Image

    job = {"id": "link:x", "company": "BETC Fullsix", "location": "Pantin, France",
           "title": "BETC Fullsix - Consultant CRM / Marketing Automation (H/F/X) CDI"}
    out = renderer.banner(job, {"score": 81, "contract": "CDI"}, {"color": "#e30613", "logo": ""}, tmp_path / "b.png")
    assert Image.open(out).size == (1260, 420)  # sharp, under Telegram's 1280 px limit
    from hunter.render import banner_html
    page = banner_html(job, {"score": 81, "contract": "CDI"}, None)
    assert "YOUR LINK" in page and ">Consultant CRM / Marketing Automation<" in page and ">BF<" in page


def test_keyword_search_is_word_based_like_a_recruiters():
    def units(*lines):
        return [re.findall(r"[a-z0-9+#]+", ats.fold(l)) for l in lines]

    cv = units("Gestion de campagnes SEA (Google Ads) pour le trafic qualifié", "Création de pages d'atterrissage")
    assert ats.covered(cv, "campagnes Google")
    assert ats.covered(cv, "pages d'atterrissages")  # the posting's own typo
    assert not ats.covered(cv, "ROI") and not ats.covered(cv, "Google Analytics")


def test_truth_check_flags_what_the_profile_does_not_back(cand, cv_en):
    text = plain_text(cv_en, cand)
    assert ats.truth_flags(text, cand) == []
    flags = ats.truth_flags(text + "\nGrew revenue by 340% with AI agents.", cand)
    assert any("340" in f for f in flags) and any("AI overclaim" in f for f in flags)
    assert ats.truth_flags("Booked a 15-minute call", cand) == []
    assert ats.unbacked_tools(text, cand) == []
    assert ats.unbacked_tools(text + "\nCRM: Odoo, HubSpot", cand) == ["names 'Odoo', which is not in the profile"]
    assert ats.unbacked_tools("Une notion de marketing", cand) == []


def test_word_cv_for_portals_keeps_the_parse_safe_order(cand, cv_fr, tmp_path):
    from hunter.docx_cv import cv_docx, docx_text

    lines, i = [l.strip() for l in docx_text(cv_docx(cv_fr, cand, tmp_path / "cv.docx")).splitlines()], 0
    assert lines[0] == cand.profile["identity"]["name"] and cand.profile["identity"]["email"] in lines[2]
    for e in (e for e in cand.profile["experience"] if e["id"] in [x["id"] for x in cv_fr["experience"]]):
        title = re.sub(r"\s*\([^()]*\)\s*$", "", e["title_fr"])
        i = lines.index(title, i)
        assert lines[i + 1] == e["company"] and lines[i + 2] == local_dates(e, "fr")
        i += 3
    assert "COMPÉTENCES CLÉS" in lines and "FORMATION" in lines


def test_an_ongoing_entry_reads_in_each_language(renderer, cand, cv_fr, tmp_path):
    cv = cv_fr | {"experience": [{"id": "courtside", "bullets": ["Création d'un **média basket indépendant**."]}]
                  + cv_fr["experience"]}
    pdf = tmp_path / "cv.pdf"
    renderer.cv_pdf(cv, cand, pdf, plain=True)
    res = ats.check(pdf, [], cv["headline"].split(" | ")[0], "fr", cand, max_pages=2, ids=[x["id"] for x in cv["experience"]])
    lines = [l.strip() for l in res["text"].splitlines()]
    i = lines.index("Fondateur & animateur")
    assert lines[i + 1:i + 3] == ["Courtside", "janv. 2025 - aujourd'hui"]
    assert res["issues"] == [], res["issues"]



def test_a_detailed_cv_runs_onto_two_full_size_pages(renderer, cand, cv_fr, tmp_path):
    """More detail in the roles that matter: two pages at full size, still read in order by an ATS."""
    facts = {e["id"]: e["facts"] for e in cand.profile["experience"]}
    exp = [x | {"bullets": [f"**{f.split()[0]} {f.split()[1]}** {' '.join(f.split()[2:])}." for f in facts[x["id"]][:6]]}
           for x in cv_fr["experience"]]
    cv = cv_fr | {"experience": exp}
    pdf = tmp_path / "cv.pdf"
    pages, scale = renderer.cv_pdf(cv, cand, pdf)
    assert pages == 2 and scale == 1.0, (pages, scale)
    res = ats.check(pdf, [], cv["headline"].split(" | ")[0], "fr", cand, max_pages=2, ids=[x["id"] for x in exp])
    assert res["sections_ok"] and not [i for i in res["issues"] if "parse" in i or "pages" in i], res["issues"]
    text = res["text"]
    order = [text.index(e["company"], text.lower().index("expérience professionnelle")) for e in cand.profile["experience"]
             if e["id"] in {x["id"] for x in exp}]
    assert order == sorted(order)

"""The plain CV as a Word file, only for strict corporate portals (Workday, Taleo, SuccessFactors...), which
read .docx best (rules in .claude/skills/ats-resume-formatting): one column, no tables, no header or footer,
standard headings, job title, employer and dates each on their own line, no bullets on education lines."""
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .brand import brand
from .candidate import Candidate
from .render import LABELS, assemble

INK, MUTED = RGBColor(0x12, 0x1A, 0x2B), RGBColor(0x5A, 0x64, 0x78)


def _accent() -> RGBColor:
    """The brand's darker accent (headings, the headline), as the designed CV uses it."""
    hex6 = brand()["accent_ink"].lstrip("#")
    return RGBColor(int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16))


def _runs(par, text: str, size: float = 10.5, color: RGBColor = INK, bold: bool = False):
    """'**Lead** rest' -> a bold run then a normal one: the same lead a recruiter sees on the PDF."""
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text or "")):
        if part:
            run = par.add_run(part)
            run.font.size, run.font.color.rgb, run.bold = Pt(size), color, bold or i % 2 == 1


def _par(doc, text: str = "", size: float = 10.5, color: RGBColor = INK, bold: bool = False, after: float = 0,
         style: str | None = None):
    par = doc.add_paragraph(style=style)
    par.paragraph_format.space_after = Pt(after)
    par.paragraph_format.space_before = Pt(0)
    par.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    _runs(par, text, size, color, bold)
    return par


def _heading(doc, text: str):
    h = doc.add_heading(level=1)
    h.paragraph_format.space_before, h.paragraph_format.space_after = Pt(10), Pt(3)
    run = h.add_run(text.upper())
    run.font.size, run.font.color.rgb, run.bold, run.font.name = Pt(11.5), _accent(), True, "Calibri"


def cv_docx(content: dict, cand: Candidate, out: Path) -> Path:
    c, lang = assemble(content, cand)
    p, L = cand.profile["identity"], LABELS[lang]
    doc = Document()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Cm(1.6)
        section.left_margin = section.right_margin = Cm(1.9)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(10.5)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "Calibri")
    doc.core_properties.author, doc.core_properties.title = p["name"], f'{p["name"]} - CV - {c["headline"]}'

    # Contact details in the body: parsers often skip Word headers and footers.
    _par(doc, p["name"], 20, INK, True, 2)
    _par(doc, c["headline"], 11.5, _accent(), True, 3)
    linkedin = p.get("linkedin_url") or p.get("linkedin_label", "")
    portfolio = p.get("portfolio_url", "") if c["portfolio"] else ""
    _par(doc, " | ".join(x for x in (p["phone"], p["email"], p["location"], linkedin, portfolio) if x), 10, MUTED,
         after=2)
    _par(doc, " · ".join(re.sub(r"<[^>]+>", "", h["html"]) for h in c["highlights"]), 10, MUTED, after=4)

    _heading(doc, L["profile"])
    _par(doc, c["summary"], after=3)
    for s in c["strengths"]:
        _par(doc, s, style="List Bullet")

    _heading(doc, L["skills"])
    for g in c["skills"]:
        par = _par(doc, after=1)
        _runs(par, f'{g["label"]}{" : " if lang == "fr" else ": "}', bold=True)
        _runs(par, ", ".join(g["items"]))

    _heading(doc, L["experience"])
    for j in c["experience"]:
        _par(doc, j["title_plain"], 11, INK, True)  # line 1: the title alone, no "(alternance)"
        _par(doc, j["company"], 10.5, INK)          # line 2: the employer alone
        _par(doc, j["dates"], 10, MUTED)            # line 3: the dates alone
        if j["note"]:
            _par(doc, j["note"], 10, MUTED)
        for b in j["bullets"]:
            _par(doc, b, style="List Bullet")
        _par(doc, after=2)

    if c["projects"]:
        _heading(doc, L["projects"])
        for x in c["projects"]:
            par = _par(doc, after=2)
            _runs(par, f'{x["name"]}{" : " if lang == "fr" else ": "}', bold=True)
            _runs(par, x["line"] + (f' {x["link"]}' if x["link"] else ""))

    _heading(doc, L["education"])
    for e in c["education"]:  # never bulleted: a bullet hides a degree from the parser
        _par(doc, e["degree"], 11, INK, True)
        _par(doc, e["school"])
        _par(doc, e["dates"], 10, MUTED)
        if e["detail"]:
            _par(doc, e["detail"], 10, MUTED)
        _par(doc, after=2)

    _heading(doc, L["certifications"])
    for cert in c["certifications"]:
        _par(doc, cert, 10.5)
    _heading(doc, L["languages"])
    _par(doc, " · ".join(lg["text"] for lg in c["languages"]))
    _heading(doc, L["achievements"])
    _par(doc, " · ".join(c["achievements"]))

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


def docx_text(path: Path) -> str:
    """What a parser reads from the Word file, paragraph by paragraph."""
    return "\n".join(par.text for par in Document(path).paragraphs)

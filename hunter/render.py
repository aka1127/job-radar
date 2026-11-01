"""Tailored CV content -> one-page PDF that looks designed and still parses cleanly."""
import base64
import html
import logging
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from functools import lru_cache

from . import logos, targets
from .ats import role_title
from .brand import brand, text, theme
from .candidate import ROOT, Candidate
from .i18n import LABELS, date_line, field
from .text import display_title, local_dates

log = logging.getLogger(__name__)

PLACES_FR = {"UAE": "Émirats arabes unis", "Spain": "Espagne", "Morocco": "Maroc", "Barcelona": "Barcelone",
             "Dubai": "Dubaï", "Lisbon": "Lisbonne"}
MIN_SCALE = 0.86  # below this the text gets too small: shorten the content instead
# Framing = the job family the CV is written for (see targets.framing). With the candidate's config it picks the
# optional parts: the creative tiles (cv.creative_families), the portfolio link in the header
# (cv.portfolio_families), the projects block and extra certifications (profile families).


def _cv_families(cand: Candidate, key: str) -> set[str]:
    return set((cand.config.get("cv") or {}).get(key) or [])

_env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html", "j2"]))


def _bold(text) -> Markup:
    """**phrase** -> <b>phrase</b>, everything else escaped: the lead a recruiter sees first."""
    parts = re.split(r"\*\*(.+?)\*\*", str(text or ""))
    return Markup("".join(f"<b>{escape(p)}</b>" if i % 2 else str(escape(p)) for i, p in enumerate(parts)))


def unbold(text: str) -> str:
    return str(text or "").replace("**", "")


def _luminance(rgb: tuple) -> float:
    lin = [c / 255 / 12.92 if c / 255 <= 0.03928 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def theme_for(color: str | None) -> dict:
    """The target company's brand color as the CV accent, darkened until text on white stays readable
    (WCAG contrast 4.5:1 for accents, about 8:1 for the darker ink). The brand's own palette when there is none."""
    if not color or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return theme()
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))

    def darker(limit: float) -> str:
        c = rgb
        while _luminance(c) > limit:
            c = tuple(int(v * 0.92) for v in c)
        return "#%02x%02x%02x" % c

    soft = tuple(round(255 - (255 - v) * 0.07) for v in rgb)
    return {"accent": darker(0.18), "accent_ink": darker(0.08), "soft": "#%02x%02x%02x" % soft}


_env.filters["bold"] = _bold


@lru_cache(maxsize=4)
def fonts_css(family: str) -> str:
    """@font-face rules embedding assets/fonts/*.woff2 under the brand's family name."""
    rules = []
    for woff in sorted((ROOT / "assets" / "fonts").glob("*.woff2")):
        rng = woff.with_suffix(".range").read_text().strip()
        data = base64.b64encode(woff.read_bytes()).decode()
        rules.append(f'@font-face {{ font-family: "{family}"; font-weight: 400 800; font-display: block; '
                     f'src: url(data:font/woff2;base64,{data}) format("woff2"); unicode-range: {rng}; }}')
    return "\n".join(rules)


def _look() -> dict:
    """What every template gets about the brand: the embedded fonts and the family name."""
    family = brand()["font"]
    return {"fonts": fonts_css(family), "font": family, "brand": brand()}


def place(s: str, lang: str) -> str:
    if lang == "fr":
        for en, fr in PLACES_FR.items():
            s = s.replace(en, fr)
    return s


def _bold_lead(text: str) -> str:
    """'6+ years of experience' -> '<b>6+ years</b> of experience' for the tiles."""
    t = html.escape(text)
    m = re.match(r"(\S+\s+\S+)(.*)", t) if re.match(r"[\d+]", t) else None
    return f"<b>{m.group(1)}</b>{m.group(2)}" if m else f"<b>{t}</b>"


# Tile icons: drawn, no text inside, so parsers see only the words next to them.
_ICON = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{}</svg>'
ICONS = {
    "briefcase": _ICON.format('<rect x="2" y="5" width="12" height="9" rx="1.6"/><path d="M5.6 5V3.7c0-.6.5-1.1 1.1-1.1h2.6c.6 0 1.1.5 1.1 1.1V5M2 9.2h12"/>'),
    "globe": _ICON.format('<circle cx="8" cy="8" r="6.2"/><path d="M1.8 8h12.4M8 1.8c1.7 1.8 2.5 3.8 2.5 6.2S9.7 12.4 8 14.2C6.3 12.4 5.5 10.4 5.5 8S6.3 3.6 8 1.8z"/>'),
    "chat": _ICON.format('<path d="M2.5 3.3h11v7.2H8l-3.2 2.6v-2.6H2.5z"/>'),
    "check": _ICON.format('<circle cx="8" cy="8" r="6.2"/><path d="M5.2 8.2l2 2 3.7-4"/>'),
    "star": _ICON.format('<path d="M8 2.2l1.8 3.8 4 .5-3 2.8.8 4L8 11.4l-3.6 1.9.8-4-3-2.8 4-.5z"/>'),
}
DEFAULT_ICONS = ["briefcase", "globe", "chat", "check"]

# The mark on the priority tag of the Telegram header (config: priority.icon), filled, 24 px.
_MARK = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="{}"/></svg>'
BANNER_ICONS = {
    "star": _MARK.format("M12 2.5l2.9 6 6.6.8-4.9 4.6 1.3 6.5L12 17.2l-5.9 3.2 1.3-6.5L2.5 9.3l6.6-.8z"),
    "music": _MARK.format("M9 3v10.6A3.8 3.8 0 1 0 11 17V8h7V3z"),
    "heart": _MARK.format("M12 21s-7.5-4.6-9.5-9A5.4 5.4 0 0 1 12 6a5.4 5.4 0 0 1 9.5 6c-2 4.4-9.5 9-9.5 9z"),
    "health": _MARK.format("M9 3h6v6h6v6h-6v6H9v-6H3V9h6z"),
    "bolt": _MARK.format("M13 2 3 14h7l-1 8 10-12h-7z"),
    "leaf": _MARK.format("M20 4c-8 0-14 4-14 12 0 2 .5 3 .5 3S8 16 14 12c-4 4-5 8-5 8s3-1 6-4c3-3 5-8 5-12z"),
    "briefcase": _MARK.format("M9 4h6v2h5v13H4V6h5zm2 0v2h2V4z"),
    "flag": _MARK.format("M5 3h2v18H5zm3 1h11l-3 4 3 4H8z"),
    "pin": _MARK.format("M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z"),
    "shield": _MARK.format("M12 2 4 5v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V5z"),
    "globe": _MARK.format("M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm6.9 9h-3a15 15 0 0 0-1.2-5.2A8 8 0 0 1 18.9 11z"
                          "M12 4a13 13 0 0 1 1.9 7h-3.8A13 13 0 0 1 12 4zM5.1 13h3a15 15 0 0 0 1.2 5.2A8 8 0 0 1 5.1 13z"
                          "m3-2h-3a8 8 0 0 1 4.2-5.2A15 15 0 0 0 8.1 11zM12 20a13 13 0 0 1-1.9-7h3.8A13 13 0 0 1 12 20z"
                          "m2.7-1.8A15 15 0 0 0 15.9 13h3a8 8 0 0 1-4.2 5.2z"),
    "trophy": _MARK.format("M6 3h12v3h3v2a5 5 0 0 1-4.3 5A6 6 0 0 1 13 16v2h3v3H8v-3h3v-2a6 6 0 0 1-3.7-3A5 5 0 0 1 3 8V6h3z"
                           "M5 8a3 3 0 0 0 1.3 2.5A9 9 0 0 1 6 8zm13 0a9 9 0 0 1-.3 2.5A3 3 0 0 0 19 8z"),
}


def _dots(level: str) -> int:
    """Language level as 0-5 dots, for the designed CV only."""
    lv = level.lower()
    if any(w in lv for w in ("native", "maternelle", "bilingual", "bilingue", "c2", "muttersprache", "nativo",
                             "nativa", "madrelingua", "moedertaal", "materna")) and "c1/c2" not in lv:
        return 5
    return 4 if "c1" in lv else 3 if "b2" in lv else 2


def _photo(cand: Candidate) -> str:
    name = cand.profile["identity"].get("photo")
    path = cand.dir / name if name else None
    if not path or not path.exists():
        return ""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def assemble(content: dict, cand: Candidate) -> tuple[dict, str]:
    """Merge AI-written parts with fixed facts. Titles, dates, schools always come from the profile."""
    lang = content.get("lang", "en")
    framing = content.get("framing") or ""
    p = cand.profile
    folder = cand.dir / "logos"
    by_id = {e["id"]: e for e in p["experience"]}
    experience = []
    badge_color = brand()["badge"]
    for item in content["experience"]:
        e = by_id.get(item["id"])
        if not e:
            continue
        logo = logos.ensure(folder, e["id"], e["company"], e.get("domain", ""), e.get("badge", ""), color=badge_color)
        title = (item.get("alt_title") and field(e, "title_alt", lang)) or field(e, "title", lang)
        split = re.match(r"(.*?)\s*\(([^()]+)\)\s*$", title)  # "Analyste (alternance)" for strict parsers
        experience.append(dict(title=title, title_plain=split.group(1) if split else title,
                               note=split.group(2).capitalize() if split else "",
                               company=field(e, "company", lang), location=place(e["location"], lang),
                               context=field(e, "context", lang), dates=local_dates(e, lang),
                               bullets=item.get("bullets", []), logo=logos.data_uri(logo)))
    education = []
    for i, e in enumerate(p["education"]):
        logo = logos.ensure(folder, f"edu-{i}", e["school"], e.get("domain", ""), e.get("badge", ""), color=badge_color)
        education.append(dict(degree=field(e, "degree", lang), school=e["school"], location=place(e["location"], lang),
                              dates=local_dates(e, lang), logo=logos.data_uri(logo),
                              detail=(framing and e.get(f"detail_{framing}_{lang}")) or field(e, "detail", lang)))
    languages = [{"text": l.get(lang) or f'{l["name"]}: {l["level"]}', "dots": _dots(l["level"])}
                 for l in p["identity"]["languages"]]
    target = content.get("target") or None
    projects = [dict(name=x["name"], line=field(x, "line", lang), link=x.get("link", ""), link_label=x.get("link_label", ""))
                for x in p.get("projects", []) if framing in x.get("families", [])]
    extra = (p.get("certifications_extra") or {}).get(framing, [])
    tiles = (framing in _cv_families(cand, "creative_families") and p.get("highlights_creative")) or p.get("highlights", [])
    return dict(headline=content["headline"], summary=content["summary"], strengths=content.get("strengths") or [],
                skills=content["skills"], experience=experience, education=education, projects=projects,
                certifications=p["certifications"] + [x for x in extra if x not in p["certifications"]],
                languages=languages,  # an achievement the projects block already tells is not repeated
                achievements=[a for a in (p.get(f"achievements_{lang}") or p.get("achievements_en") or [])
                              if not any(x["name"] in a for x in projects)],
                portfolio=framing in _cv_families(cand, "portfolio_families") and bool(p["identity"].get("portfolio_url")),
                highlights=[{"html": _bold_lead(h.get(lang) or h.get("en") or ""),
                             "icon": ICONS.get(h.get("icon") or DEFAULT_ICONS[min(i, 3)], ICONS["star"])}
                            for i, h in enumerate(tiles)], target=target), lang


def html_for(content: dict, cand: Candidate, scale: float = 1.0, plain: bool = False) -> str:
    """plain=True: no logos, icons, photo or tinted band, for strict corporate ATS portals."""
    c, lang = assemble(content, cand)
    return _env.get_template("cv.html.j2").render(c=c, p=cand.profile["identity"], L=LABELS[lang], lang=lang,
                                                  scale=scale, photo=_photo(cand), plain=plain,
                                                  show_portfolio=c["portfolio"], **_look(),
                                                  theme=theme() if plain else theme_for((c["target"] or {}).get("color")))


def letter_html(letter: str, job: dict, headline: str, cand: Candidate, lang: str, scale: float = 1.0,
                color: str | None = None, framing: str = "") -> str:
    today = date.today()
    when = date_line(cand.profile['identity']['location'].split(',')[0], lang, today)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", letter.strip()) if p.strip()]
    return _env.get_template("letter.html.j2").render(
        p=cand.profile["identity"], L=LABELS[lang], lang=lang, scale=scale, photo="", plain=False, **_look(),
        theme=theme_for(color), show_portfolio=framing in _cv_families(cand, "portfolio_families"),
        headline=headline, company=job["company"], title=display_title(job["title"]), place_date=when,
        paragraphs=paragraphs)


def banner_html(job: dict, fit: dict, target: dict | None, cfg: dict | None = None) -> str:
    """Telegram header for one job: the company's brand color and logo, its name, the role and the fit score.
    A job in the candidate's priority sector gets the brand's priority look instead of the company's colors."""
    target, cfg = target or {}, cfg or {}
    logo = Path(target["logo"]) if target.get("logo") else None
    words = [w for w in re.split(r"[\s&'.-]+", job["company"]) if w[:1].isalnum()]
    size = len(job["company"])
    p = targets.priority(cfg) if targets.is_priority(fit, cfg) else {}
    tag = (text("tag_priority", tag=p.get("tag") or "PRIORITY") if p
           else text("tag_link") if job["id"].startswith("link:") else text("tag_new"))
    return _env.get_template("banner.html.j2").render(
        theme=theme_for(target.get("color")), company=job["company"] or "?", **_look(),
        company_px=70 if size <= 9 else 56 if size <= 14 else 44,
        title=display_title(role_title(job["title"], job["company"])), score=fit["score"], fit_label=text("fit"),
        priority=bool(p), icon_svg=BANNER_ICONS.get(str(p.get("icon") or "star"), BANNER_ICONS["star"]) if p else "",
        tag=tag, logo=logos.data_uri(logo) if logo and logo.exists() else "",
        initials="".join(w[0] for w in words[:2]).upper() or "?")


def plain_text(content: dict, cand: Candidate) -> str:
    """Text an ATS would extract. Used for keyword coverage and truth checks."""
    c, _ = assemble(content, cand)
    parts = [c["headline"], unbold(c["summary"]), *map(unbold, c["strengths"])]
    parts += [f'{g["label"]}: {", ".join(g["items"])}' for g in c["skills"]]
    for j in c["experience"]:
        parts += [j["title"], *map(unbold, j["bullets"])]
    parts += [f'{x["name"]}: {x["line"]}' for x in c["projects"]]
    return "\n".join(parts)


class Renderer:
    """One headless browser reused for every PDF in a run."""

    def __enter__(self):
        for attempt in range(3):
            self._pw = sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch()
                return self
            except Exception as e:
                # A half-started Playwright breaks every later launch in this process: always stop it.
                self._pw.stop()
                if attempt == 2:
                    raise
                log.warning("PDF browser launch failed, retrying: %s", str(e).splitlines()[0][:200])
                if "Executable doesn't exist" in str(e):  # browser files gone: fetch them again
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], timeout=900)
                time.sleep(15)

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    def _fit(self, make_html, out: Path, max_pages: int = 1, keep_one_above: float | None = None) -> tuple[int, float]:
        """The largest scale (down to MIN_SCALE) that fits max_pages. With keep_one_above, a document that fits one
        page with only a slight squeeze stays on one page; one that needs more goes onto a second page at full
        size: readable and complete beats short. Returns (pages, scale); more pages than max_pages means too long."""
        out.parent.mkdir(parents=True, exist_ok=True)
        page = self._browser.new_page()

        def pages_at(scale: float) -> int:
            page.set_content(make_html(scale), wait_until="load")
            page.evaluate("document.fonts.ready")
            page.pdf(path=str(out), format="A4", print_background=True)
            return len(PdfReader(out).pages)

        def largest(floor: float, n: int) -> tuple[int, float]:
            lo, hi = floor, 1.0  # largest scale that still fits n pages
            while hi - lo > 0.01:
                mid = round((lo + hi) / 2, 3)
                lo, hi = (mid, hi) if pages_at(mid) <= n else (lo, mid)
            return pages_at(lo), lo

        try:
            full = pages_at(1.0)
            if full == 1:
                return 1, 1.0
            if keep_one_above and pages_at(keep_one_above) == 1:
                return largest(keep_one_above, 1)
            if full <= max_pages:
                return pages_at(1.0), 1.0
            if pages_at(MIN_SCALE) > max_pages:
                return len(PdfReader(out).pages), MIN_SCALE
            return largest(MIN_SCALE, max_pages)
        finally:
            page.close()

    def cv_pdf(self, content: dict, cand: Candidate, out: Path, plain: bool = False) -> tuple[int, float]:
        # One page only when it fits at a readable size (otherwise page 2 would hold a few lines); else two full pages.
        return self._fit(lambda s: html_for(content, cand, s, plain), out, max_pages=2,
                         keep_one_above=0.95 if plain else MIN_SCALE)

    def letter_pdf(self, letter: str, job: dict, headline: str, cand: Candidate, lang: str, out: Path,
                   color: str | None = None, framing: str = "") -> tuple[int, float]:
        return self._fit(lambda s: letter_html(letter, job, headline, cand, lang, s, color, framing), out)

    def banner(self, job: dict, fit: dict, target: dict | None, out: Path, cfg: dict | None = None) -> Path:
        page = self._browser.new_page(viewport={"width": 900, "height": 300}, device_scale_factor=1.4)
        try:
            page.set_content(banner_html(job, fit, target, cfg), wait_until="load")
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(out))
        finally:
            page.close()
        return out

    def screenshot(self, html_str: str, out: Path):
        """PNG preview of a page, for reviewing designs."""
        page = self._browser.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=1.5)
        try:
            page.set_content(html_str, wait_until="load")
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(out), full_page=False)
        finally:
            page.close()

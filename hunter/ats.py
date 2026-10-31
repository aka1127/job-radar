"""Read the PDF back the way an ATS does and score it like the common resume checkers, then catch
anything the profile does not back."""
import re
from pathlib import Path

from pypdf import PdfReader

from .text import clean_title, fold, local_dates

SECTIONS = {
    "en": ["profile", "key skills", "professional experience", "education"],
    "fr": ["profil", "competences cles", "experience professionnelle", "formation"],
}
BAD_GLYPHS = re.compile("[ﬀ-ﬆ�-]")
YEARS = re.compile(r"\b(19|20)\d\d\b")


def pdf_text(path: Path) -> tuple[str, int]:
    reader = PdfReader(path)
    return "\n".join(p.extract_text() or "" for p in reader.pages), len(reader.pages)


def has(text_folded: str, phrase: str) -> bool:
    f = fold(phrase)
    return len(f.strip()) > 0 and f in text_folded


STOP = {"de", "des", "du", "la", "le", "les", "et", "en", "pour", "avec", "sur", "au", "aux", "un", "une", "d", "l",
        "a", "the", "and", "of", "for", "to", "in", "on", "with", "an", "or", "ou"}


def _stems(phrase: str) -> list[str]:
    """'Campagnes Google' -> ['campag', 'google']: plurals, gender and accents do not matter."""
    words = re.findall(r"[a-z0-9+#]+", fold(phrase))
    return [(w.rstrip("s") if len(w) > 4 else w)[:6] for w in words if w not in STOP]


def covered(lines: list[list[str]], keyword: str) -> bool:
    """A recruiter's keyword search: every key word of the phrase on one CV line (bullet, skills row...)."""
    stems = _stems(keyword)
    return bool(stems) and any(all(any(t.startswith(s) for t in line) for s in stems) for line in lines)


def role_title(posting_title: str, company: str = "") -> str:
    """'BETC Fullsix - Consultant CRM (H/F)' -> 'Consultant CRM (H/F)' when the prefix names the company."""
    head, sep, rest = posting_title.partition(" - ")
    first = fold(company).split()[0] if fold(company).split() else ""
    return rest if sep and first and f" {first} " in fold(head) and len(rest.split()) >= 2 else posting_title


def check(pdf: Path, keywords: list[str], posting_title: str, lang: str, cand, company: str = "",
          max_pages: int = 1, ids: list[str] | None = None) -> dict:
    """max_pages=2 for the plain CV: corporate portals read parsed fields, and 10pt beats squeezing to one page."""
    posting_title = role_title(posting_title, company)
    raw, pages = pdf_text(pdf)
    t = fold(raw)
    issues: list[str] = []

    kws = list(dict.fromkeys(k for k in keywords if k.strip()))
    words = [re.findall(r"[a-z0-9+#]+", fold(l)) for l in raw.splitlines()]
    units = [a + b for a, b in zip(words, words[1:] + [[]])]  # a bullet can wrap onto the next line
    found = [k for k in kws if has(t, k) or covered(units, k)]
    missing = [k for k in kws if k not in found]
    coverage = len(found) / len(kws) if kws else 1.0

    title_ok = clean_title(posting_title) in fold(raw[:400])
    if not title_ok:
        issues.append("headline does not repeat the posting's job title")

    # Parsing: sections in the standard order, contact details, every job with its title and dates.
    lines = [fold(l).strip() for l in raw.splitlines()]
    positions = [lines.index(s) if s in lines else -1 for s in (fold(x).strip() for x in SECTIONS[lang])]
    sections_ok = all(p >= 0 for p in positions) and positions == sorted(positions)
    if not sections_ok:
        issues.append("standard sections missing or out of order in the extracted text")
    ident = cand.profile["identity"]
    contact = [ident["email"].lower() in raw.lower(), bool(re.search(r"\+?\d[\d .]{8,}", raw)),
               has(t, ident["location"].split(",")[0]), has(fold(raw[:200]), ident["name"])]
    if not all(contact):
        issues.append("contact block not fully readable (name, email, phone, city)")
    # The plain CV puts "(alternance)" on its own line, so the title only has to match without it.
    jobs = [e for e in cand.profile["experience"] if ids is None or e["id"] in ids]  # the jobs this CV shows
    jobs_ok = [any(has(t, re.sub(r"\s*\([^()]*\)\s*$", "", e[k])) for k in (f"title_{lang}", f"title_alt_{lang}") if e.get(k))
               and has(t, e.get(f"company_{lang}") or e["company"])
               and re.search(r"\d{4}", local_dates(e, lang)).group(0) in raw for e in jobs] or [True]
    if not all(jobs_ok):
        issues.append("some job titles, companies or dates did not parse")
    parse = (sections_ok + sum(contact) / 4 + sum(jobs_ok) / len(jobs_ok)) / 3

    # Format: one page, clean characters, sensible length.
    glyphs = BAD_GLYPHS.findall(raw)
    words = len(raw.split())
    most = 900 if max_pages == 1 else 1500
    fmt = [pages <= max_pages, not glyphs, 350 <= words <= most]
    if pages > max_pages:
        issues.append(f"{pages} pages")
    if glyphs:
        issues.append("unreadable characters in the extracted text")
    if not 350 <= words <= most:
        issues.append(f"{words} words (aim for 350-{most})")

    # Impact: bullets with real numbers (years excluded).
    bullets = [l for l in raw.splitlines() if len(l) > 60]
    quantified = sum(bool(re.search(r"\d", YEARS.sub("", l))) for l in bullets)
    impact = min(1.0, quantified / 4)
    if impact < 0.5:
        issues.append("few measurable results: add real numbers to the profile metrics")

    score = round(55 * coverage + 10 * title_ok + 20 * parse + 10 * sum(fmt) / 3 + 5 * impact)
    return dict(score=score, coverage=round(100 * coverage), found=found, missing=missing, title_match=title_ok,
                sections_ok=sections_ok, pages=pages, words=words, issues=issues, text=raw)


# Tools a writer might copy from a posting. Case-sensitive on purpose ("Notion" the app, not "la notion de").
TOOLS = ["HubSpot", "Salesforce", "Marketo", "Pardot", "SFMC", "Adobe Campaign", "Brevo", "Sendinblue", "Klaviyo",
         "Mailchimp", "ActiveCampaign", "Lemlist", "Hootsuite", "Sprout Social", "Semrush", "SEMrush", "Ahrefs", "Moz",
         "Screaming Frog", "Looker", "Tableau", "Power BI", "SQL", "BigQuery", "Python", "Figma", "Canva", "Webflow",
         "WordPress", "Shopify", "Zapier", "n8n", "Notion", "Asana", "Jira", "Monday.com", "Trello", "Hotjar",
         "Optimizely", "AB Tasty", "Contentsquare", "LinkedIn Ads", "TikTok Ads", "Snapchat Ads", "Criteo", "DV360",
         "Odoo", "Zoho", "Pipedrive", "Intercom", "Zendesk", "Trustpilot", "Microsoft Dynamics", "Amplitude",
         "Mixpanel", "Braze", "Iterable", "Airtable", "Clay", "Sales Navigator", "Dripify", "Manatal", "Reply.io",
         "Matomo", "AT Internet", "Google Tag Manager", "Google Analytics", "GA4", "Search Console", "Meta Ads",
         "Google Ads", "Microsoft Ads", "Amazon Ads", "Adobe Analytics", "Typeform", "Unbounce", "Wix", "Drupal",
         "Contentful", "Sitecore", "Photoshop", "Illustrator", "Premiere Pro", "After Effects", "InDesign", "CapCut",
         "Midjourney", "ChatGPT", "Gemini", "Perplexity", "Copilot", "Excel", "PowerPoint", "Tableau"]


def unbacked_tools(cv_text: str, cand) -> list[str]:
    """Tools named on the CV that appear nowhere in the profile (not even as 'to confirm')."""
    profile = fold(cand.profile_raw)
    return [f"names '{t}', which is not in the profile" for t in dict.fromkeys(TOOLS)
            if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", cv_text) and not has(profile, t)]


def truth_flags(cv_text: str, cand, posting: str = "") -> list[str]:
    """Things in the CV or letter that the profile does not back. Shown before anything is sent.
    Numbers quoted from the posting (company size, team...) are fine."""
    flags = []
    backed = fold(cand.profile_raw.split("to_confirm:")[0])
    text_lower = cv_text.lower()
    for tool in cand.profile["skills"]["to_confirm"]:
        # Exact phrase only: "HubSpot, workflows CRM" is not a claim of "HubSpot workflows".
        phrase = r"(?<![\w-])" + r"\s+".join(map(re.escape, tool.lower().split())) + r"(?![\w-])"
        if re.search(phrase, text_lower) and not has(backed, tool):
            flags.append(f"mentions '{tool}', which is not confirmed in the profile")
    backed_ai = fold(cand.profile_raw)
    for m in re.finditer(r"AI workflows?|workflows? (?:d['’])?IA\b|AI agents?|agents? IA\b|AI strategy|stratégie IA\b",
                         cv_text, re.I):
        if not has(backed_ai, m.group(0)):
            flags.append(f"AI overclaim: '{m.group(0)}'")
    known = set(re.findall(r"\d+(?:[.,]\d+)?", cand.profile_raw + posting))
    claims = re.sub(r"\b\d+\s*-?\s*(min|minute|minutes|mn)\b", " ", cv_text, flags=re.I)  # "15-minute call"
    for n in set(re.findall(r"\d+(?:[.,]\d+)?", claims)):
        if n not in known and not YEARS.fullmatch(n):
            flags.append(f"number '{n}' is not in the profile")
    return flags

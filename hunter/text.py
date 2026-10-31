"""Small text helpers shared by the pipeline."""
import re
import unicodedata

from . import i18n

# Applied after fold(): "(F/H/X)" has become "f h x".
TITLE_NOISE = r"\b[hfmwdx]( [hfmwdx]){1,2}\b|\b(cdi|cdd|stage|freelance|full remote|remote|hybride?|teletravail)\b"

def fold(s: str) -> str:
    """Lowercase, no accents, words separated by single spaces, padded so ' seo ' matches whole words."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9+#]+", " ", s).strip() + " "


def clean_title(title: str) -> str:
    t = fold(re.sub(r"\((e|ne|se|s)\)", "", title or "", flags=re.I))
    return re.sub(r"\s+", " ", re.sub(TITLE_NOISE, " ", t)).strip()


def display_title(title: str) -> str:
    """Job title without gender markers or contract tags: "Chef de projet (H/F) - CDI" -> "Chef de projet"."""
    t = re.sub(r"\s*[\(\[]\s*(?:[HFMWX]|NB)(?:\s*/\s*(?:[HFMWXD]|NB))+\s*[\)\]]", "", title or "", flags=re.I)
    t = re.sub(r"\s*\b(?:[HF]\s*/\s*[HF](?:\s*/\s*(?:X|NB))?)\b", "", t, flags=re.I)
    t = re.sub(r"\s*[-–|]\s*(?:CDI|CDD|Stage|Alternance|Freelance)\b.*$", "", t, flags=re.I)
    return re.sub(r"\s+(?:CDI|CDD)\s*$", "", t, flags=re.I).strip(" -–|")


def local_dates(entry: dict, lang: str) -> str:
    """Dates as the profile writes them ('Oct 2024 - Sep 2025'), in the CV's language ('oct. 2024 - sept. 2025')."""
    return i18n.local_dates(entry.get(f"dates_{lang}") or entry["dates"], lang)


def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s).strip())[:n].strip("-") or "job"


def detect_lang(text: str) -> str | None:
    """The posting's language (en, fr, es, de, it, pt, nl) by common-word counts; None when too short to tell."""
    return i18n.detect(text)

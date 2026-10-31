"""Small text helpers shared by the pipeline."""
import re
import unicodedata

# Applied after fold(): "(F/H/X)" has become "f h x".
TITLE_NOISE = r"\b[hfmwdx]( [hfmwdx]){1,2}\b|\b(cdi|cdd|stage|freelance|full remote|remote|hybride?|teletravail)\b"

FR_WORDS = {"le", "la", "les", "des", "du", "et", "vous", "nous", "pour", "avec", "une", "est", "sur", "dans",
            "au", "aux", "votre", "notre", "nos", "vos", "sont", "qui", "que", "ou", "chez", "ainsi", "mais", "être"}
EN_WORDS = {"the", "and", "you", "we", "for", "with", "our", "to", "of", "is", "are", "your", "will", "be",
            "this", "that", "as", "on", "who", "what", "about", "into", "from", "have", "an", "at"}


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


MONTHS_FR = {"Jan": "janv.", "Feb": "févr.", "Mar": "mars", "Apr": "avr.", "May": "mai", "Jun": "juin",
             "Jul": "juil.", "Aug": "août", "Sep": "sept.", "Oct": "oct.", "Nov": "nov.", "Dec": "déc."}


def local_dates(entry: dict, lang: str) -> str:
    """Dates as the profile writes them ('Oct 2024 - Sep 2025'), in the CV's language ('oct. 2024 - sept. 2025')."""
    dates = entry.get(f"dates_{lang}") or entry["dates"]
    if lang == "fr":
        dates = re.sub(r"\b(" + "|".join(MONTHS_FR) + r")\b", lambda m: MONTHS_FR[m.group(1)], dates)
        dates = dates.replace("Present", "aujourd'hui")
    return dates


def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s).strip())[:n].strip("-") or "job"


def detect_lang(text: str) -> str | None:
    """French or English by common-word counts. None when the text is too short to tell."""
    words = re.findall(r"[a-zàâäçéèêëîïôöûùüÿœ]+", (text or "").lower())
    fr = sum(w in FR_WORDS for w in words)
    en = sum(w in EN_WORDS for w in words)
    if fr + en < 15:
        return None
    return "fr" if fr > en else "en"

"""Countries and places, for any country: is a job's location in the candidate's country, and is it within reach of
their home? Country names, codes, cities and coordinates come from GeoNames (the geonamescache package: every
country, every city of more than 15,000 people, CC BY 4.0)."""
import math
import re
from functools import lru_cache

from .i18n import LABELS
from .text import fold

# Names job postings and people use for a country that GeoNames does not give as its English name (folded).
ALIASES = {
    "FR": ["france", "ile de france", "idf", "la defense", "sophia antipolis"],
    "GB": ["uk", "united kingdom", "great britain", "britain", "england", "scotland", "wales", "northern ireland",
           "royaume uni", "angleterre"],
    "US": ["usa", "united states", "united states of america", "u s a", "america", "etats unis"],
    "DE": ["deutschland", "allemagne", "germania"], "ES": ["espana", "espagne", "spagna"],
    "IT": ["italia", "italie"], "NL": ["nederland", "holland", "the netherlands", "pays bas"],
    "BE": ["belgique", "belgie", "belgien"], "CH": ["suisse", "schweiz", "svizzera", "svizra"],
    "AT": ["osterreich", "autriche"], "PT": [], "IE": ["eire", "irlande"], "SE": ["sverige"], "DK": ["danmark"],
    "NO": ["norge"], "FI": ["suomi"], "PL": ["polska", "pologne"],
    "CZ": ["czechia", "cesko", "czech republic", "ceska republika", "republique tcheque"],
    "MA": ["maroc", "marokko", "marruecos"], "DZ": ["algerie"], "TN": ["tunisie"],
    "AE": ["uae", "emirates", "united arab emirates"], "SA": ["ksa"], "MX": ["mexico"], "BR": ["brasil"],
    "CA": ["canada"], "LU": ["letzebuerg", "luxemburg"], "GR": ["hellas"], "TR": ["turkiye"], "IN": ["bharat"],
    "KR": ["korea", "republic of korea", "coree du sud"], "KP": ["north korea"], "CI": ["cote d ivoire", "cote divoire"],
    "MK": ["macedonia", "north macedonia"], "RU": ["russian federation", "russie"], "VN": ["viet nam"],
    "CV": ["cabo verde"], "SZ": ["swaziland"], "MM": ["burma"], "TL": ["east timor"], "PS": ["palestine"],
    "CD": ["drc", "congo kinshasa"], "CG": ["congo brazzaville"], "MD": ["moldavie"], "LB": ["liban"],
}
# "Remote" in the languages the engine writes CVs in (folded: no accents).
REMOTE = re.compile(r"\b(remote|remoto|full remote|teletravail|teletrabajo|teletrabalho|telework|home ?office|"
                    r"smart working|work from home|thuiswerk(?:en)?|fernarbeit|mobiles arbeiten|lavoro da remoto)\b")
LATIN = re.compile(r"[A-Za-zÀ-ÿĀ-ſ' .-]+")  # alternate names worth matching (not Cyrillic, Arabic, CJK...)


@lru_cache(maxsize=1)
def _world() -> tuple[dict, dict, dict, list]:
    """(country name -> code, code -> country, city name -> (population, code), cities)."""
    import geonamescache

    gc = geonamescache.GeonamesCache(min_city_population=15000)
    countries = gc.get_countries()
    names = {fold(c["name"]).strip(): code for code, c in countries.items()}
    for code, extra in ALIASES.items():
        names.update({a: code for a in extra})
    for state in gc.get_us_states().values():  # "Austin, Texas": a state names its country
        names[fold(state["name"]).strip()] = "US"
    cities = list(gc.get_cities().values())
    best: dict[str, tuple[int, str]] = {}
    for c in cities:
        spellings = {c["name"]}
        if c["population"] >= 300_000:  # big cities under their local names too: München, Milano, Lisboa
            spellings |= {a for a in c["alternatenames"] if len(a) >= 4 and LATIN.fullmatch(a)}
        for s in spellings:
            key = fold(s).strip()
            if key and key not in names and (key not in best or c["population"] > best[key][0]):
                best[key] = (c["population"], c["countrycode"])
    return names, countries, best, cities


def country_code(text: str) -> str | None:
    """'Germany', 'Deutschland', 'de', 'UK' -> the ISO code; None when it names no country."""
    t = (text or "").strip()
    if t.upper() in _world()[1]:
        return t.upper()
    return {"uk": "GB"}.get(t.lower()) or _world()[0].get(fold(t).strip())


def country_name(code: str) -> str:
    return _world()[1].get(code.upper(), {}).get("name", code)


def country_language(code: str) -> str:
    """The country's main language the engine can write CVs in (FR -> fr, DE -> de, BR -> pt, LU -> fr since
    Luxembourgish CVs are not supported), else English."""
    langs = _world()[1].get(code.upper(), {}).get("languages", "")
    for lang in langs.split(","):
        short = lang.split("-")[0].strip().lower()
        if short in LABELS:
            return short
    return "en"


def _grams(text: str, n: int = 4) -> set[str]:
    words = fold(text).split()
    return {" ".join(words[i:i + k]) for k in range(1, n + 1) for i in range(len(words) - k + 1)}


def countries_in(location: str) -> set[str]:
    """Countries a location names outright: "Berlin, Germany", "Remote - France", "Lisbon (PT)"."""
    names = _world()[0]
    found = {names[g] for g in _grams(location) if g in names}
    m = re.search(r"(?:^|[\s,(/-])([A-Z]{2,3})\)?\s*$", (location or "").strip())  # a trailing country code
    if not found and m:
        code = m.group(1)
        iso3 = {c["iso3"]: k for k, c in _world()[1].items()}
        found |= {code} if code in _world()[1] else {iso3[code]} if code in iso3 else set()
    return found


def in_country(location: str, code: str) -> bool:
    """A job is in the country when its location names that country, or else names one of its cities (a city name
    belongs to the country of its biggest namesake: Paris is in France, London in the UK)."""
    code = code.upper()
    named = countries_in(location)
    if named:
        return code in named
    best = _world()[2]
    return any(best[g][1] == code for g in _grams(location) if g in best)


def _distance_km(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _spellings(c: dict) -> set[str]:
    """Every folded spelling of a city: GeoNames' name and its Latin alternate names (Munich, München, Monaco di
    Baviera...), so the home and the postings may each use their own."""
    names = {fold(c["name"]).strip()}
    names |= {fold(a).strip() for a in c.get("alternatenames") or [] if len(a) >= 3 and LATIN.fullmatch(a)}
    return {n for n in names if n}


def _home_city(home: str, code: str) -> dict | None:
    """The GeoNames city (15,000+ people) the home names in that country, under any of its spellings; the biggest
    when several share the name. None for a smaller town or a typo."""
    city = fold((home or "").split(",")[0]).strip()
    if not city:
        return None
    homes = [c for c in _world()[3] if c["countrycode"] == code.upper() and city in _spellings(c)]
    return max(homes, key=lambda c: c["population"]) if homes else None


def home_known(home: str, code: str) -> bool:
    """False when the home is not a GeoNames city: the radius then covers nothing but the name itself."""
    return _home_city(home, code) is not None


@lru_cache(maxsize=16)
def home_area(home: str, code: str, radius_km: float = 40) -> frozenset[str]:
    """Every spelling of every city within radius_km of the home city, the home city included. When the home is
    unknown to GeoNames (a town under 15,000 people, a typo), just the name as written."""
    city = fold((home or "").split(",")[0]).strip()
    center = _home_city(home, code)
    if not center:
        return frozenset({city} if city else set())
    area: set[str] = set()
    for c in _world()[3]:
        if c["countrycode"] == code.upper() and _distance_km(center, c) <= radius_km:
            area |= _spellings(c)
    return frozenset(area)


def near(location: str, area: frozenset[str]) -> bool:
    """The location names a place of the home area, or the job is remote."""
    return bool(REMOTE.search(fold(location))) or bool(_grams(location) & area)

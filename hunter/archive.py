"""The archive: every job posting any source returns, whatever the candidate, in one database per machine.
One row per posting: seeing it again only refreshes last_seen and keeps the longest description. For a candidate in
France the place is also reduced to a département (rules below, then the official commune directory) so the archive
can be counted by area; elsewhere the French rules stay off (Archive(french=False))."""
import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .candidate import HOME
from .store import dedupe_key
from .text import fold

log = logging.getLogger(__name__)
DB = HOME / "data" / "jobs.db"
GEO = "https://geo.api.gouv.fr/communes"  # official French commune directory, free and open
SCHEMA = """
create table if not exists postings (
    id text primary key, key text, source text, title text, company text, location text, postcode text,
    department text, contract text, rome text, posted text, url text, apply_url text, description text,
    first_seen text, last_seen text, extra text);
create index if not exists postings_key on postings(key);
create index if not exists postings_posted on postings(posted);
create index if not exists postings_department on postings(department);
create index if not exists postings_source on postings(source);
create index if not exists postings_first_seen on postings(first_seen);
create table if not exists meta (k text primary key, v text);
create table if not exists places (name text primary key, department text);
"""
# Fields of a job dict that are kept as columns; the rest (except per-candidate hints) goes into `extra`.
COLUMNS = ("id", "site", "source", "title", "company", "location", "postcode", "department", "contract", "rome",
           "posted", "url", "apply_url", "description")
NOT_KEPT = {"tier_hint", "tries", "score_tries"}
CITY_DEPARTMENT = {
    "paris": "75", "marseille": "13", "lyon": "69", "villeurbanne": "69", "toulouse": "31", "nice": "06",
    "nantes": "44", "montpellier": "34", "strasbourg": "67", "bordeaux": "33", "lille": "59", "rennes": "35",
    "reims": "51", "toulon": "83", "saint etienne": "42", "le havre": "76", "rouen": "76", "grenoble": "38",
    "dijon": "21", "angers": "49", "nimes": "30", "clermont ferrand": "63", "le mans": "72", "aix en provence": "13",
    "brest": "29", "tours": "37", "amiens": "80", "limoges": "87", "annecy": "74", "perpignan": "66", "metz": "57",
    "besancon": "25", "orleans": "45", "mulhouse": "68", "caen": "14", "nancy": "54", "pau": "64", "bayonne": "64",
    "la rochelle": "17", "poitiers": "86", "avignon": "84", "valence": "26", "chambery": "73", "vannes": "56",
    "lorient": "56", "quimper": "29", "saint malo": "35", "arras": "62", "calais": "62", "dunkerque": "59",
    "roubaix": "59", "tourcoing": "59", "villeneuve d ascq": "59", "colmar": "68", "troyes": "10", "chartres": "28",
    "beauvais": "60", "laval": "53", "niort": "79", "angouleme": "16", "bourges": "18", "blois": "41",
    "boulogne billancourt": "92", "la defense": "92", "nanterre": "92", "courbevoie": "92", "puteaux": "92",
    "issy les moulineaux": "92", "levallois perret": "92", "neuilly sur seine": "92", "clichy": "92",
    "montrouge": "92", "rueil malmaison": "92", "saint denis": "93", "montreuil": "93", "saint ouen": "93",
    "pantin": "93", "creteil": "94", "vincennes": "94", "ivry sur seine": "94", "rungis": "94", "versailles": "78",
    "massy": "91", "evry": "91", "cergy": "95", "argenteuil": "95", "roissy": "95", "marne la vallee": "77",
    "sophia antipolis": "06", "ajaccio": "2A", "bastia": "2B",
}


DEPARTMENT_NAMES = {
    "ain": "01", "aisne": "02", "allier": "03", "alpes de haute provence": "04", "hautes alpes": "05",
    "alpes maritimes": "06", "ardeche": "07", "ardennes": "08", "ariege": "09", "aube": "10", "aude": "11",
    "aveyron": "12", "bouches du rhone": "13", "calvados": "14", "cantal": "15", "charente": "16",
    "charente maritime": "17", "cher": "18", "correze": "19", "cote d or": "21", "cotes d armor": "22",
    "creuse": "23", "dordogne": "24", "doubs": "25", "drome": "26", "eure": "27", "eure et loir": "28",
    "finistere": "29", "corse du sud": "2A", "haute corse": "2B", "gard": "30", "haute garonne": "31", "gers": "32",
    "gironde": "33", "herault": "34", "ille et vilaine": "35", "indre": "36", "indre et loire": "37", "isere": "38",
    "jura": "39", "landes": "40", "loir et cher": "41", "loire": "42", "haute loire": "43", "loire atlantique": "44",
    "loiret": "45", "lot": "46", "lot et garonne": "47", "lozere": "48", "maine et loire": "49", "manche": "50",
    "marne": "51", "haute marne": "52", "mayenne": "53", "meurthe et moselle": "54", "meuse": "55",
    "morbihan": "56", "moselle": "57", "nievre": "58", "nord": "59", "oise": "60", "orne": "61",
    "pas de calais": "62", "puy de dome": "63", "pyrenees atlantiques": "64", "hautes pyrenees": "65",
    "pyrenees orientales": "66", "bas rhin": "67", "haut rhin": "68", "rhone": "69", "haute saone": "70",
    "saone et loire": "71", "sarthe": "72", "savoie": "73", "haute savoie": "74", "seine maritime": "76",
    "seine et marne": "77", "yvelines": "78", "deux sevres": "79", "somme": "80", "tarn": "81",
    "tarn et garonne": "82", "var": "83", "vaucluse": "84", "vendee": "85", "vienne": "86", "haute vienne": "87",
    "vosges": "88", "yonne": "89", "territoire de belfort": "90", "essonne": "91", "hauts de seine": "92",
    "seine saint denis": "93", "val de marne": "94", "val d oise": "95", "guadeloupe": "971", "martinique": "972",
    "guyane": "973", "la reunion": "974", "reunion": "974", "mayotte": "976",
}
REGIONS = {"ile de france": "11", "idf": "11", "auvergne rhone alpes": "84", "hauts de france": "32",
           "provence alpes cote d azur": "93", "paca": "93", "grand est": "44", "occitanie": "76", "normandie": "28",
           "nouvelle aquitaine": "75", "centre val de loire": "24", "bourgogne franche comte": "27", "bfc": "27",
           "bretagne": "53", "pays de la loire": "52", "corse": "94"}
NOT_A_TOWN = {"france", "fr", "teletravail", "remote", "full remote", "hybride", "hybrid", "europe", "emea", ""}


def _segments(location: str) -> list[str]:
    return [fold(p).strip() for p in re.split(r"[,/|]", location or "")]


TRAILING = re.compile(r"\s+(" + "|".join(sorted(map(re.escape, [*REGIONS, "fr", "france"]), key=len, reverse=True))
                      + r")$")


def town(location: str) -> tuple[str, str]:
    """('gentilly', '11') for 'Gentilly, Île-de-France, France': the town to look up, and its region when named.
    Also reads places written without commas: 'Choisy-le-Roi IDF fr' -> ('choisy le roi', '11')."""
    parts = _segments(location)
    region = next((REGIONS[p] for p in parts if p in REGIONS), "")
    for p in parts:
        name = re.sub(r"\b(cedex|\d+(er|e|eme)?|arrondissement)\b", " ", p)
        name = re.sub(r"\bst\b", "saint", name)
        name = re.sub(r"\s+", " ", name).strip()
        while (m := TRAILING.search(name)) and m.start() > 0:  # 'choisy le roi idf fr' -> 'choisy le roi'
            region = region or REGIONS.get(m.group(1), "")
            name = name[:m.start()].strip()
        words = name.split()
        if len(words) % 2 == 0 and words[:len(words) // 2] == words[len(words) // 2:]:  # 'vanves vanves'
            name = " ".join(words[:len(words) // 2])
        if len(name) > 1 and name not in NOT_A_TOWN and name not in REGIONS and name not in DEPARTMENT_NAMES:
            return name, region
    return "", region


def department(location: str, postcode: str = "") -> str:
    """'Paris 09 - 75' -> '75', '75011' -> '75', '97400' -> '974', '2A004' -> '2A', 'Lyon 3e' -> '69', else ''."""
    for text in (postcode or "", location or ""):
        if m := re.search(r"\b(97[1-6])\d{2}\b", text):  # overseas départements have three digits
            return m.group(1)
        if m := re.search(r"\b(2[AB])\d{3}\b", text):  # Corsica, INSEE commune codes
            return m.group(1)
        if m := re.search(r"\b(\d{5})\b", text):
            code = m.group(1)
            return ("2A" if code < "20200" else "2B") if code.startswith("20") else code[:2]
    loc = location or ""
    if m := re.search(r"^\s*(\d{2,3}|2[AB])\s+-\s|\s-\s(\d{2,3}|2[AB])\s*$|\((\d{2,3}|2[AB])\)|"
                      r",\s*(\d{2,3}|2[AB])\s*(?:,|$)", loc):
        return next(g for g in m.groups() if g)
    if dep := next((DEPARTMENT_NAMES[p] for p in _segments(loc) if p in DEPARTMENT_NAMES), ""):
        return dep
    folded = fold(loc)
    return next((dep for city, dep in CITY_DEPARTMENT.items() if f" {city} " in folded), "")


def _row(job: dict, seen: str, dep: str | None = None) -> tuple:
    """dep: the département decided by save() ("" outside France); None computes it with the French rules."""
    extra = {k: v for k, v in job.items() if k not in COLUMNS and k not in NOT_KEPT and v not in ("", None, [], {})}
    if isinstance(job.get("extra"), dict):
        extra = {k: v for k, v in extra.items() if k != "extra"} | job["extra"]
    if dep is None:
        dep = job.get("department") or department(job.get("location") or "", job.get("postcode") or "")
    return (job["id"], dedupe_key(job), job.get("source") or job.get("site") or "", job.get("title") or "",
            job.get("company") or "", job.get("location") or "", job.get("postcode") or "", dep,
            job.get("contract") or "", job.get("rome") or "", job.get("posted") or "", job.get("url") or "",
            job.get("apply_url") or "", job.get("description") or "", seen, seen,
            json.dumps(extra, ensure_ascii=False, default=str))


class Archive:
    def __init__(self, path: Path | None = None, french: bool = True):
        """french=False (a candidate outside France): no département parsing, no commune lookups."""
        path = path or DB  # read at call time, so tests can point it elsewhere
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=60, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self.french = french

    def lookup(self, location: str) -> str:
        """The département of a town the rules do not know, from the official commune directory; cached, so each
        town is asked once. Inside a named region (Saint-Denis, Île-de-France) the answer stays in that region."""
        name, region = town(location)
        if not name:
            return ""
        key = f"{name}|{region}"
        row = self.db.execute("select department from places where name=?", (key,)).fetchone()
        if row:
            return row[0]
        params = {"nom": name, "fields": "codeDepartement", "boost": "population", "limit": 1}
        if region:
            params["codeRegion"] = region
        try:
            hits = requests.get(GEO, params=params, timeout=8).json()
        except (requests.RequestException, ValueError) as e:
            log.info("commune lookup failed for %s: %s", name, e)
            return ""  # not cached: asked again next time
        dep = (hits[0].get("codeDepartement") or "") if isinstance(hits, list) and hits else ""
        with self._lock:
            self.db.execute("insert or replace into places (name, department) values (?, ?)", (key, dep))
        return dep

    def save(self, jobs: list[dict], lookups: int = 300) -> int:
        """Store every posting; returns how many were not in the archive yet. Up to `lookups` unknown towns are
        looked up per call (the others get their département when seen again)."""
        jobs = [j for j in jobs if j.get("id") and j.get("title")]
        if not jobs:
            return 0
        deps = {}
        for j in jobs:
            dep = j.get("department") or (department(j.get("location") or "", j.get("postcode") or "") if self.french else "")
            if not dep and self.french and lookups > 0 and j.get("location"):
                lookups -= 1
                dep = self.lookup(j["location"])
            deps[j["id"]] = dep or ""
        seen = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            ids = [j["id"] for j in jobs]
            known = set()
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                known |= {r[0] for r in self.db.execute(
                    f"select id from postings where id in ({','.join('?' * len(chunk))})", chunk)}
            self.db.executemany("""
                insert into postings (id, key, source, title, company, location, postcode, department, contract,
                                      rome, posted, url, apply_url, description, first_seen, last_seen, extra)
                values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                on conflict(id) do update set last_seen=excluded.last_seen,
                    description=case when length(excluded.description) > length(coalesce(postings.description, ''))
                                     then excluded.description else postings.description end,
                    contract=coalesce(nullif(excluded.contract, ''), postings.contract),
                    company=coalesce(nullif(postings.company, ''), excluded.company),
                    department=coalesce(nullif(postings.department, ''), excluded.department),
                    extra=excluded.extra""", [_row(j, seen, deps[j["id"]]) for j in jobs])
            self.db.commit()
        return len(set(ids) - known)

    def recent(self, since: str, sources: tuple[str, ...]) -> list[dict]:
        """Postings first seen since `since` from the given sources, as job dicts for a candidate's run."""
        if not sources:
            return []
        rows = self.db.execute(
            f"select * from postings where first_seen>=? and source in ({','.join('?' * len(sources))})",
            (since, *sources)).fetchall()
        out = []
        for r in rows:
            extra = json.loads(r["extra"] or "{}")
            out.append({"id": r["id"], "site": r["source"], "title": r["title"], "company": r["company"],
                        "location": r["location"], "url": r["url"], "apply_url": r["apply_url"], "posted": r["posted"],
                        "description": r["description"], "company_url": "", "contract": r["contract"]}
                       | {k: extra[k] for k in ("ends", "contractuels") if k in extra})
        return out

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("select v from meta where k=?", (key,)).fetchone()
        return row[0] if row else default

    def put(self, key: str, value: str):
        with self._lock:
            self.db.execute("insert into meta (k, v) values (?, ?) on conflict(k) do update set v=excluded.v",
                            (key, value))
            self.db.commit()

    def stats(self) -> dict:
        """What the archive holds: totals, freshness, and the split by source, area and contract."""
        q = lambda sql, *a: self.db.execute(sql, a).fetchall()  # noqa: E731
        day = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        return {
            "postings": q("select count(*) from postings")[0][0],
            "companies": q("select count(distinct lower(company)) from postings where company!=''")[0][0],
            "new_last_24h": q("select count(*) from postings where first_seen>=?", day)[0][0],
            "seen_last_24h": q("select count(*) from postings where last_seen>=?", day)[0][0],
            "by_source": dict(q("select source, count(*) n from postings group by source order by n desc")),
            "by_department": dict(q("select coalesce(nullif(department, ''), '?'), count(*) n from postings "
                                    "group by 1 order by n desc limit 20")),
            "by_contract": dict(q("select coalesce(nullif(contract, ''), '?'), count(*) n from postings "
                                  "group by 1 order by n desc limit 10")),
        }

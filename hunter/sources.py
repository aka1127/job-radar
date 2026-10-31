"""Job boards (LinkedIn, Indeed, Glassdoor, HelloWork in France) and France Travail's official API (France only).
Phase 1 reads cheap search-result pages. Phase 2 opens a job page only for postings that passed the
filters, which keeps LinkedIn and HelloWork from rate-limiting us."""
import html
import logging
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

log = logging.getLogger(__name__)
BOARDS = ("linkedin", "indeed", "hellowork", "glassdoor")
# Reposts that name a job board as the employer (Glassdoor carries HelloWork's offers as "Hellowork"): the real
# company is unknown and the board itself is searched directly, so they are skipped.
BOARD_COMPANY = re.compile(r"^(hellowork|indeed|jobijoba|meteojob|monster|cadremploi|talent\.com|jooble|optioncarriere|"
                           r"glassdoor|linkedin|welcome to the jungle|jobteaser|keljob|regionsjob)$", re.I)


class RateLimitWatch(logging.Handler):
    """JobSpy logs HTTP 429/403 instead of raising. Leave that board alone for the rest of the run."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.blocked: set[str] = set()

    def emit(self, record):
        msg = record.getMessage()
        if " 429" in msg or " 403" in msg or "blocked" in msg:
            board = next((b for b in BOARDS if b in record.name.lower()), None)
            if board and board not in self.blocked:
                log.warning("%s is rate-limiting us: pausing it until the next run", board)
                self.blocked.add(board)


WATCH = RateLimitWatch()
logging.getLogger("jobspy").addHandler(WATCH)


def job(**kw) -> dict:
    keys = ("id", "site", "title", "company", "location", "url", "apply_url", "posted", "description", "company_url")
    out = {k: str(kw.get(k) or "").strip() for k in keys}
    for k in ("title", "company", "location"):  # some feeds escape twice: "DIGITAL &amp; B2B" -> "DIGITAL & B2B"
        out[k] = html.unescape(out[k])
    return out


JOBSPY_NAMES = {"US": "usa", "GB": "uk", "CZ": "czech republic", "TR": "türkiye"}


def jobspy_country(code: str) -> str | None:
    """The country name JobSpy expects for Indeed and Glassdoor ("france", "usa"...), None when it has none."""
    from jobspy.model import Country

    from . import geo
    name = JOBSPY_NAMES.get(code.upper(), geo.country_name(code).lower())
    return name if name in {c.value for c in Country} else None


def board_works(site: str, code: str) -> bool:
    """HelloWork is French; Indeed and Glassdoor need a country JobSpy knows; LinkedIn searches by place."""
    return code.upper() == "FR" if site == "hellowork" else bool(jobspy_country(code)) if site in ("indeed", "glassdoor") else True


def listing(site: str, term: str, location: str, hours: int, n: int, country: str = "FR") -> list[dict]:
    from jobspy import scrape_jobs

    try:
        # Glassdoor sends descriptions 25 jobs per request: cheap enough to take them with the listing.
        df = scrape_jobs(site_name=[site], search_term=term, location=location, results_wanted=n,
                         hours_old=hours, country_indeed=jobspy_country(country) or "usa", description_format="markdown",
                         fetch_description=site == "glassdoor", verbose=1)  # 1 keeps the 429 warnings RateLimitWatch needs
    except Exception as e:  # one failing board must never kill the run
        log.warning("%s '%s' failed: %s", site, term, e)
        return []
    out = []
    for r in df.fillna("").to_dict("records"):
        if BOARD_COMPANY.match(str(r.get("company") or "").strip()):
            continue
        out.append(job(id=f'{site}:{r.get("id") or r.get("job_url")}', site=site, title=r.get("title"),
                       company=r.get("company"), location=r.get("location"), url=r.get("job_url"),
                       apply_url=r.get("job_url_direct"), posted=r.get("date_posted"),
                       description=r.get("description"),
                       company_url=r.get("company_url_direct") or r.get("company_url")))
    return out


class Details:
    """Open single job pages with JobSpy's own parsers (version pinned in requirements.txt)."""

    def __init__(self):
        self._scrapers: dict = {}

    def _scraper(self, site: str):
        if site not in self._scrapers:
            from jobspy.model import ScraperInput, Site
            from jobspy.util import RequestsRotating, TLSRotating, create_session

            inp = ScraperInput(site_name=[Site(site)], description_format="markdown")
            if site == "linkedin":
                from jobspy.linkedin import LinkedIn
                from jobspy.linkedin.constant import headers
                s = LinkedIn()
                s.session = create_session(RequestsRotating(None, clear_cookies=True), inp, headers)
            else:
                from jobspy.hellowork import HelloWork
                s = HelloWork()
                s.session = create_session(TLSRotating(None), inp)
            s.scraper_input = inp
            self._scrapers[site] = s
        return self._scrapers[site]

    def fetch(self, j: dict) -> str:
        site = j["site"]
        if site not in ("linkedin", "hellowork") or site in WATCH.blocked:
            return ""
        raw_id = j["id"].split(":", 1)[1].removeprefix("li-").removeprefix("hw-")
        try:
            s = self._scraper(site)
            d = s._fetch_details(raw_id) if site == "linkedin" else s._fetch_details(raw_id, j["url"])
        except Exception as e:
            log.warning("details failed for %s: %s", j["url"], e)
            return ""
        return (d or {}).get("description") or ""


def linkedin_job(url: str) -> dict | None:
    """A LinkedIn job link -> full posting (title, company, location from the page, description via JobSpy)."""
    from bs4 import BeautifulSoup

    m = re.search(r"linkedin\.com/.*?(?:jobs/view/(?:[^/?#]*?-)?(\d{6,})|currentJobId=(\d{6,}))", url)
    if not m:
        return None
    jid = m.group(1) or m.group(2)
    d = Details()
    page = d._scraper("linkedin").session.get(f"https://www.linkedin.com/jobs/view/{jid}")
    soup = BeautifulSoup(page.text, "html.parser")
    title = soup.select_one("h1.top-card-layout__title") or soup.select_one("h1")
    head = soup.title.get_text(" ", strip=True) if soup.title else ""
    company = re.search(r" at (.+?) (?:—|\||-) ", head)
    where = soup.select_one("span.topcard__flavor--bullet")
    j = job(id=f"linkedin:li-{jid}", site="linkedin", url=f"https://www.linkedin.com/jobs/view/{jid}",
            title=title.get_text(" ", strip=True) if title else "", company=company.group(1) if company else "",
            location=where.get_text(" ", strip=True) if where else "")
    j["description"] = d.fetch(j)
    return j if j["title"] and len(j["description"]) >= 200 else None


class FranceTravail:
    """Official France Travail 'Offres d'emploi v2' API (free app at francetravail.io)."""

    TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
    SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

    def __init__(self):
        self.cid = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
        self.secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")
        self._token, self._expires = None, 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.cid and self.secret)

    def _auth(self) -> str:
        """A token lasts about 25 minutes: a long harvest asks for a new one a minute before it expires."""
        if not self._token or time.time() > self._expires - 60:
            r = requests.post(self.TOKEN_URL, timeout=30, data={
                "grant_type": "client_credentials", "client_id": self.cid,
                "client_secret": self.secret, "scope": "api_offresdemploiv2 o2dsoffre"})
            r.raise_for_status()
            data = r.json()
            self._token, self._expires = data["access_token"], time.time() + float(data.get("expires_in") or 1400)
        return self._token

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self._auth()}", "Accept": "application/json"}

    def reset(self):
        self._token = None

    def search(self, term: str, tier: int, hours: int, departments: list[str] = ()) -> list[dict]:
        days = next((d for d in (1, 3, 7, 14, 31) if d * 24 >= hours), 31)
        params = {"motsCles": term, "publieeDepuis": days, "range": "0-49"}
        if tier == 1 and departments:  # the home region
            params["departement"] = ",".join(list(departments)[:5])  # the API takes at most 5
        try:
            r = requests.get(self.SEARCH_URL, timeout=30, params=params,
                             headers={"Authorization": f"Bearer {self._auth()}"})
            if r.status_code == 204:
                return []
            r.raise_for_status()
        except Exception as e:
            log.warning("france_travail '%s' failed: %s", term, e)
            return []
        out = []
        for o in r.json().get("resultats", []):
            origin = (o.get("origineOffre") or {}).get("urlOrigine")
            out.append(job(id=f'france_travail:{o["id"]}', site="france_travail", title=o.get("intitule"),
                           company=(o.get("entreprise") or {}).get("nom"),
                           location=(o.get("lieuTravail") or {}).get("libelle"),
                           url=origin or f'https://candidat.francetravail.fr/offres/recherche/detail/{o["id"]}',
                           apply_url=origin, posted=(o.get("dateCreation") or "")[:10],
                           description=o.get("description"), company_url=(o.get("entreprise") or {}).get("url")))
        return out


def _board(site: str, cfg: dict, hours: int) -> tuple[list[dict], int]:
    """Every search term and location on one board, one after the other with pauses (each board paces itself)."""
    sc = cfg["scraping"]
    # Broad places first: when "France" returns fewer results than asked, it already holds every
    # "Paris, France" match, so that search is skipped (half the requests on most hourly runs).
    locations = sorted(cfg["locations"], key=lambda l: len(l["query"]))
    jobs: list[dict] = []
    searches = 0
    for term in cfg["searches"]:
        complete: list[str] = []
        for loc in locations:
            if site in WATCH.blocked:
                return jobs, searches
            if any(loc["query"].endswith(c) for c in complete):
                continue
            batch = listing(site, term, loc["query"], hours, sc["results_per_search"], cfg.get("country") or "FR")
            searches += 1
            if len(batch) < sc["results_per_search"]:
                complete.append(loc["query"])
            for j in batch:
                j["tier_hint"] = str(loc["tier"])
            jobs += batch
            time.sleep(random.uniform(*sc["pause_between_searches_s"]))
    return jobs, searches


def _france_travail(cfg: dict, hours: int) -> tuple[list[dict], int]:
    ft = FranceTravail()
    if not ft.enabled:
        return [], 0
    home = sorted(str(d) for d in cfg.get("home_departments") or [])
    jobs = [j for term in cfg["searches"] for loc in cfg["locations"] for j in ft.search(term, loc["tier"], hours, home)]
    return jobs, len(cfg["searches"]) * len(cfg["locations"])


def collect(cand, hours: dict[str, int]) -> list[dict]:
    """Phase 1 on every board, location and search term. hours: how far back each board looks.
    The boards run side by side (each keeps its own pace), so adding a board barely lengthens a run."""
    cfg = cand.config
    WATCH.blocked.clear()  # a block lasts one run, also inside the long-running loop
    code = (cfg.get("country") or "FR").upper()
    sites = [s for s in BOARDS if cfg["sources"].get(s) and s in hours and board_works(s, code)]
    work = [(s, lambda s=s: _board(s, cfg, hours[s])) for s in sites]
    if cfg["sources"].get("france_travail") and code == "FR":
        work.append(("france_travail", lambda: _france_travail(cfg, max(hours.values(), default=24))))
    jobs: list[dict] = []
    searches = 0
    if work:
        with ThreadPoolExecutor(len(work)) as pool:
            for found, n in pool.map(lambda w: w[1](), work):
                jobs += found
                searches += n
    log.info("boards: %d postings from %d searches (blocked: %s)", len(jobs), searches,
             ", ".join(sorted(WATCH.blocked)) or "none")
    return jobs

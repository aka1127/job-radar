"""Company career sites, for jobs that never reach LinkedIn or the job boards.

Most companies publish jobs through an ATS with a public job-board API (meant for embedding on their
own site): Lever, Greenhouse, Ashby, Workable, SmartRecruiters, Teamtailor, Recruitee, Personio.
Custom career sites usually carry schema.org JobPosting data for Google for Jobs, read here too.

The watchlist grows by itself: every apply link seen on the boards reveals a company's ATS, company
names get probed, and Claude searches the web for more career pages once a day."""
import html
import json
import logging
import random
import re
import threading
import time
import warnings
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from protego import Protego

from . import geo, targets
from .sources import BOARD_COMPANY, job
from .text import fold, slug

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
IN_FRANCE = re.compile(
    r"\b(france|fr|paris|ile de france|idf|lyon|marseille|lille|bordeaux|toulouse|nantes|nice|montpellier|rennes|"
    r"strasbourg|grenoble|la defense|levallois|boulogne|neuilly|issy|saint denis|nanterre|courbevoie|puteaux|"
    r"clichy|montrouge|vincennes|saint mande|saint ouen|aix en provence|sophia antipolis|annecy|tours|dijon|"
    r"angers|reims|rouen|caen|metz|nancy|clermont ferrand|limoges|orleans|brest|le mans|pau|biarritz)\b")
ATS_URLS = [
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([^/?#]+)"),
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([^/?#&]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([^/?#]+)"),
    ("workable", r"apply\.workable\.com/([^/?#]+)"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([^/?#]+)"),
    ("teamtailor", r"([a-z0-9-]+)\.teamtailor\.com"),
    ("recruitee", r"([a-z0-9-]+)\.recruitee\.com"),
    ("personio", r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
    ("workday", r"([a-z0-9-]+\.wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
]
NOT_SLUGS = {"embed", "api", "jobs", "careers", "www", "search", "o", "j"}
# Job boards are covered elsewhere (or not at all); the watchlist is for company sites.
JOB_BOARDS = ("linkedin.", "indeed.", "hellowork.", "welcometothejungle.", "welcomekit.", "glassdoor.", "apec.fr",
              "monster.", "jobteaser.", "francetravail.", "pole-emploi.", "meteojob.", "cadremploi.", "jobijoba.")


def get(url: str, **kw) -> requests.Response | None:
    for attempt in range(2):
        try:
            r = requests.get(url, headers=UA, timeout=40, **kw)
            if "charset" not in r.headers.get("content-type", "").lower():  # else requests assumes Latin-1
                r.encoding = r.apparent_encoding or "utf-8"
            return r
        except requests.RequestException as e:
            if attempt:
                log.info("career page unreachable %s: %s", url, e)
            time.sleep(2)
    return None


def text_of(markup: str) -> str:
    return BeautifulSoup(html.unescape(markup or ""), "html.parser").get_text("\n", strip=True)


_robots: dict[str, tuple[float, Protego | None]] = {}
_robots_lock = threading.Lock()


def allowed(url: str) -> bool:
    """robots.txt lets anyone ("*") fetch this page. Read once a day per site; no robots.txt (404) means allowed,
    an unreachable or failing one (5xx) means not now."""
    parts = urlparse(url)
    base = f"{parts.scheme}://{parts.netloc}"
    with _robots_lock:
        cached = _robots.get(base)
    if not cached or time.time() - cached[0] > 24 * 3600:
        try:
            r = requests.get(base + "/robots.txt", headers=UA, timeout=15)
            rules = Protego.parse(r.text) if r.ok else (None if r.status_code < 500 else Protego.parse("User-agent: *\nDisallow: /"))
        except requests.RequestException:
            rules = Protego.parse("User-agent: *\nDisallow: /")
        cached = (time.time(), rules)
        with _robots_lock:
            _robots[base] = cached
    return cached[1] is None or cached[1].can_fetch(url, "*")


def page_get(url: str, **kw) -> requests.Response | None:
    """A web page (not an API), fetched only when the site's robots.txt allows it."""
    if not allowed(url):
        log.info("robots.txt disallows %s: skipped", url)
        return None
    return get(url, **kw)


def page_text(page_html: str) -> str:
    """Readable text of a whole web page: the main content (trafilatura) when it finds enough of it, else the page
    without scripts, styles, menus or footers."""
    try:
        import trafilatura

        main = trafilatura.extract(page_html, include_comments=False, include_tables=True, favor_recall=True)
        if main and len(main) >= 200:
            return main
    except Exception:  # an odd page must never stop a crawl
        pass
    soup = BeautifulSoup(page_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))


def in_france(location: str) -> bool:
    return bool(IN_FRANCE.search(fold(location)))


COUNTRY, HOME = "FR", ""  # the candidate's country (ISO code) and home city, set by poll() from the config


def in_area(location: str, empty: bool = False) -> bool:
    """The posting is in the candidate's country. empty: the answer for a posting with no location at all (a
    board added for its jobs in the country usually means there)."""
    if not (location or "").strip():
        return empty
    return in_france(location) if COUNTRY == "FR" and in_france(location) else geo.in_country(location, COUNTRY)


def parse_ats_url(url: str) -> tuple[str, str] | None:
    for ats, pattern in ATS_URLS:
        m = re.search(pattern, url or "", re.I)
        if m and m.group(1).lower() not in NOT_SLUGS:
            return ats, "/".join(m.groups())  # workday: "tenant.wdN/site"
    return None


def _date(value) -> str:
    if not value:
        return ""
    if isinstance(value, (int, float)) or str(value).isdigit():
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).date().isoformat()
    return str(value)[:10]


def _job(ats: str, slug: str, company: str, jid, title, location, url, posted, description) -> dict:
    return job(id=f"{ats}:{slug}:{jid}", site=f"career page ({ats})", title=title, company=company,
               location=location, url=url, apply_url=url, posted=_date(posted), description=description)


# providers: each returns France-based postings whose title passes title_ok -----------------------

def _lever(path: str) -> requests.Response | None:
    """EU boards (jobs.eu.lever.co) answer only on Lever's EU API host."""
    for host in ("api.lever.co", "api.eu.lever.co"):
        r = get(f"https://{host}/v0/postings/{path}")
        if r is not None and r.ok:
            return r
    return None


def lever(slug, company, title_ok):
    r = _lever(f"{slug}?mode=json")
    for p in (r.json() if r is not None else []):
        cat = p.get("categories") or {}
        loc = " / ".join(cat.get("allLocations") or [cat.get("location") or ""]) + f" {p.get('country') or ''}"
        if not title_ok(p.get("text", "")) or not in_area(loc):
            continue
        desc = "\n\n".join([p.get("descriptionPlain", ""),
                            *[f"{l.get('text')}\n{text_of(l.get('content'))}" for l in p.get("lists", [])],
                            p.get("additionalPlain", "")])
        yield _job("lever", slug, company, p["id"], p["text"], loc.strip(), p["hostedUrl"], p.get("createdAt"), desc)


def greenhouse(slug, company, title_ok):
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")  # EU boards included
    for p in (r.json().get("jobs", []) if r is not None and r.ok else []):
        loc = " / ".join([(p.get("location") or {}).get("name") or "",
                          *[(o.get("location") or o.get("name") or "") for o in p.get("offices", [])]])
        if not title_ok(p.get("title", "")) or not in_area(loc):
            continue
        yield _job("greenhouse", slug, p.get("company_name") or company, p["id"], p["title"], loc,
                   p["absolute_url"], p.get("first_published") or p.get("updated_at"), text_of(p.get("content")))


def ashby(slug, company, title_ok):
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    for p in (r.json().get("jobs", []) if r is not None and r.ok else []):
        country = ((p.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or ""
        loc = " / ".join([p.get("location") or "", *[s.get("location", "") for s in p.get("secondaryLocations") or []],
                          country])
        if not p.get("isListed", True) or not title_ok(p.get("title", "")) or not in_area(loc):
            continue
        yield _job("ashby", slug, company, p["id"], p["title"], loc, p["jobUrl"], p.get("publishedAt"),
                   p.get("descriptionPlain") or text_of(p.get("descriptionHtml")))


def workable(slug, company, title_ok):
    r = get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    if r is None or not r.ok:
        return
    data = r.json()
    for p in data.get("jobs", []):
        locs = [f"{l.get('city', '')} {l.get('country', '')}" for l in p.get("locations") or []]
        loc = " / ".join(locs or [f"{p.get('city', '')} {p.get('country', '')}"])
        if not title_ok(p.get("title", "")) or not in_area(loc):
            continue
        yield _job("workable", slug, data.get("name") or company, p.get("shortcode"), p["title"], loc,
                   p.get("url") or p.get("shortlink"), p.get("published_on") or p.get("created_at"),
                   text_of(p.get("description")))


def smartrecruiters(slug, company, title_ok):
    r = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?country={COUNTRY.lower()}&limit=100")
    for p in (r.json().get("content", []) if r is not None and r.ok else []):
        loc = p.get("location") or {}
        where = f"{loc.get('city', '')} {loc.get('region', '')} {loc.get('country', '')}"
        if not title_ok(p.get("name", "")):
            continue
        d = get(p["ref"])
        if d is None or not d.ok:
            continue
        d = d.json()
        sections = (d.get("jobAd") or {}).get("sections") or {}
        desc = "\n\n".join(f"{s.get('title', '')}\n{text_of(s.get('text'))}" for s in sections.values())
        yield _job("smartrecruiters", slug, (p.get("company") or {}).get("name") or company, p["id"], p["name"],
                   where, d.get("postingUrl") or d.get("applyUrl"), p.get("releasedDate"), desc)


def _tt_host(slug: str) -> str:
    """Teamtailor boards live on <slug>.teamtailor.com or on the company's own domain (careers.shine.co)."""
    return slug if "." in slug else f"{slug}.teamtailor.com"


def teamtailor(slug, company, title_ok):
    r = get(f"https://{_tt_host(slug)}/jobs.rss?per_page=500")  # without per_page the feed stops at 100
    if r is None or not r.ok:
        return
    root = ET.fromstring(r.content)
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        loc = " ".join(t.text or "" for t in item.iter() if t.tag.split("}")[-1] in ("city", "country", "name"))
        if not title_ok(title) or not in_area(loc, empty=True):
            continue
        link = item.findtext("link") or ""
        yield _job("teamtailor", slug, company, link.rstrip("/").split("/")[-1], title, loc, link,
                   item.findtext("pubDate"), text_of(item.findtext("description")))


def recruitee(slug, company, title_ok):
    r = get(f"https://{slug}.recruitee.com/api/offers/")
    for p in (r.json().get("offers", []) if r is not None and r.ok else []):
        loc = f"{p.get('location', '')} {p.get('city', '')} {p.get('country', '')}"
        if not title_ok(p.get("title", "")) or not in_area(loc):
            continue
        yield _job("recruitee", slug, p.get("company_name") or company, p["id"], p["title"], loc, p.get("careers_url"),
                   p.get("published_at"), text_of(f"{p.get('description', '')}{p.get('requirements', '')}"))


def personio(slug, company, title_ok):
    for tld in ("de", "com"):
        r = get(f"https://{slug}.jobs.personio.{tld}/xml?language=fr")
        if r is not None and r.ok and b"<workzag-jobs" in r.content[:500]:
            break
    else:
        return
    for p in ET.fromstring(r.content).iter("position"):
        title, loc = p.findtext("name") or "", p.findtext("office") or ""
        if not title_ok(title) or not in_area(loc):
            continue
        desc = "\n\n".join(f"{d.findtext('name')}\n{text_of(d.findtext('value'))}" for d in p.iter("jobDescription"))
        yield _job("personio", slug, company, p.findtext("id"), title, loc,
                   f"https://{slug}.jobs.personio.{tld}/job/{p.findtext('id')}", p.findtext("createdAt"), desc)


def _workday_parts(slug: str) -> tuple[str, str, str]:
    """'umusic.wd5/UMGFRA' -> ('umusic.wd5.myworkdayjobs.com', 'umusic', 'UMGFRA')."""
    host, site = slug.split("/", 1)
    return f"{host}.myworkdayjobs.com", host.split(".")[0], site


def workday(slug, company, title_ok, max_jobs: int = 300):
    """Workday career sites (Universal Music France, Warner Music, Live Nation...) through the public JSON API their
    own pages use. A large global board is searched for France and Paris instead of listed in full."""
    host, tenant, site = _workday_parts(slug)
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    def page(text: str, offset: int) -> dict:
        try:
            r = requests.post(f"{api}/jobs", json={"appliedFacets": {}, "limit": 20, "offset": offset,
                                                   "searchText": text}, headers=UA | headers, timeout=30)
            return r.json() if r.ok else {}
        except (requests.RequestException, ValueError):
            return {}

    first = page("", 0)
    searches = [""] if (first.get("total") or 0) <= max_jobs else [geo.country_name(COUNTRY), *([HOME] if HOME else [])]
    seen = set()
    for text in searches:
        offset, data = 0, first if text == "" else page(text, 0)
        total = min(data.get("total") or 0, max_jobs)  # Workday gives the total on the first page only
        while data.get("jobPostings"):
            for p in data["jobPostings"]:
                path, title, loc = p.get("externalPath", ""), p.get("title", ""), p.get("locationsText", "")
                if path in seen or not title_ok(title) or not (in_area(loc) or re.match(r"\d+ locations", loc, re.I)):
                    continue
                seen.add(path)
                try:
                    d = requests.get(api + path, headers=UA | headers, timeout=30)
                    info = (d.json() if d.ok else {}).get("jobPostingInfo") or {}
                except (requests.RequestException, ValueError):
                    info = {}
                where = info.get("location") or loc
                if not info or not in_area(f"{where} {(info.get('country') or {}).get('descriptor', '')}"):
                    continue
                yield _job("workday", slug, company, info.get("jobReqId") or path, info.get("title") or title, where,
                           info.get("externalUrl") or f"https://{host}/{site}{path}", info.get("startDate"),
                           text_of(info.get("jobDescription")))
            offset += 20
            if offset >= total:
                break
            data = page(text, offset)


PROFILCULTURE = "https://www.profilculture.com/annonce/"


def profilculture_job(url: str, page_html: str) -> dict | None:
    """One ProfilCulture offer. Its pages carry no JobPosting data but a fixed layout: after "offre", the title,
    the organisation, the place, the date (dd/mm/yy) and the contract, then the description up to "Postulez"."""
    lines = [l.strip() for l in page_text(page_html).splitlines() if l.strip()]
    try:
        i = lines.index("offre")
        head = [l for l in lines[i + 1:i + 8] if l.lower() != "urgent"]  # an "Urgent" badge can sit before the contract
        title, company, place, day, contract = head[:5]
        body = lines[lines.index("Secteur", i):lines.index("Postulez", i)]
    except ValueError:
        return None
    d = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2})", day)
    posted = f"20{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else ""
    jid = re.search(r"-(\d{4,})\.html", url)
    return job(id=f"profilculture:{jid.group(1) if jid else url}", site="ProfilCulture", title=title, company=company,
               location=place, url=url, apply_url=url, posted=posted,
               description=f"Contrat : {contract}\n" + "\n".join(body))


def profilculture(slug, company, title_ok):
    """ProfilCulture, the French culture job board (live music, festivals, labels, events): a category's latest
    offers. Every offer there is in France; only titles that pass the filter are opened."""
    r = page_get(PROFILCULTURE + slug)
    if r is None or not r.ok:
        return
    soup = BeautifulSoup(r.text, "html.parser")
    seen = set()
    for a in soup.find_all("a", href=re.compile(r"/annonce/[\w-]+-\d{4,}\.html")):
        url = urljoin(PROFILCULTURE, a["href"])
        title = a.get_text(" ", strip=True)
        if url in seen or not title or not title_ok(title):
            continue
        seen.add(url)
        d = page_get(url)
        j = profilculture_job(url, d.text) if d is not None and d.ok else None
        if j and title_ok(j["title"]):
            yield j
        time.sleep(random.uniform(0.5, 1.5))


WTTJ = "https://www.welcometothejungle.com/fr/pages/"
WTTJ_JOB = re.compile(r"^/fr/companies/[^/]+/jobs/[^/?#]+$")


_wttj_rest_until = 0.0


def _wttj_get(url: str):
    """One page, or None while Welcome to the Jungle asks us to slow down: a 202 is its bot check, which is never
    worked around; the board then rests for 3 hours."""
    global _wttj_rest_until
    if time.time() < _wttj_rest_until:
        return None
    r = page_get(url)
    if r is not None and r.status_code == 202:
        _wttj_rest_until = time.time() + 3 * 3600
        log.info("Welcome to the Jungle asks to slow down: resting it for 3 hours")
        return None
    return r if r is not None and r.ok else None


def wttj(slug, company, title_ok, seen=None, max_offers: int = 8):
    """Welcome to the Jungle: a job-title page (/fr/pages/emploi-social-media-manager) lists its 20 newest offers.
    robots.txt allows these pages and the offers (only search URLs with "?" are off limits). An offer is opened only
    when its title passes the filter and it was not read on an earlier poll, a few seconds apart."""
    r = _wttj_get(WTTJ + slug)
    if r is None:
        return
    titles: dict[str, str] = {}
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=WTTJ_JOB):
        text = a.get_text(" ", strip=True)  # each offer has an image link (no text) and its title link
        if text:
            titles.setdefault(urljoin(r.url, a["href"]), text)
    todo = [u for u, t in titles.items() if title_ok(t) and not (seen and seen(u))][:max_offers]
    for url in todo:
        time.sleep(random.uniform(3, 6))
        page = _wttj_get(url)
        for d in postings_on(page.text) if page is not None else []:
            j = from_posting(d, url, "Welcome to the Jungle")
            if j["title"] and in_france(j["location"] or "france"):
                yield j | {"id": "wttj:" + url.rsplit("/jobs/", 1)[-1], "url": url, "apply_url": url}
            break


REF_PREFIX = re.compile(r"^(?=[\w/.-]*\d)[\w/.-]+\s+-\s+")  # "2026-27480 - Responsable..." -> "Responsable..."
CONTRACT = re.compile(r"\b(CDI|CDD|Stage|Alternance|Apprentissage|Int[ée]rim|Freelance|VIE)\b", re.I)
PLACE_LINE = re.compile(r"(?:Localisation|Lieu(?: de travail)?|Ville|Site)\s*:\s*([^\n]{2,80})", re.I)


def _feed_items(xml: bytes) -> list:
    """Items of an RSS or Atom feed, read leniently: some feeds end cut short or are slightly malformed."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return BeautifulSoup(xml, "html.parser").find_all(["item", "entry"])


def _feed_date(value: str) -> str:
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return (value or "")[:10] if re.match(r"\d{4}-\d{2}-\d{2}", value or "") else ""


def _feed(url: str, company: str, title_ok, multi: bool):
    r = page_get(url)
    if r is None or not r.ok:
        return
    opened = 0
    for it in _feed_items(r.content):
        def text(name):
            el = it.find(name)
            return el.get_text(" ", strip=True) if el else ""
        link_el = it.find("link")
        link = ""
        if link_el is not None:  # RSS puts the URL inside <link>, Atom in href; the lenient parser may leave it after
            link = (link_el.get("href") or link_el.get_text(strip=True) or str(link_el.next_sibling or "")).strip()
        title = REF_PREFIX.sub("", html.unescape(text("title"))).strip()
        body = it.find("description") or it.find("summary") or it.find("content")
        desc = text_of(body.get_text()) if body is not None else ""
        cats = [c.get_text(" ", strip=True) for c in it.find_all("category")]
        lines = [l.strip() for l in desc.splitlines() if l.strip()]
        firm, place = company, ""
        if multi and lines:  # a board's feed: "Company - " then "City   CDI   ..." (Stratégies emploi)
            firm = lines[0].split(" - ", 1)[0].rstrip(" -").strip()
            if lines[0].rstrip().endswith("-") and len(lines) > 1:  # "Company -" alone, then "City   CDI   ..."
                place = re.split(r"\s{2,}", lines[1])[0]
        if m := PLACE_LINE.search(desc):
            place = place or m.group(1).strip()
        if not title or not link or BOARD_COMPANY.match(firm.strip()):
            continue
        if place and not in_area(f"{place} {' '.join(cats)}"):
            continue
        if len(desc) < 200 and title_ok(title) and opened < 10:  # short summary: read the offer page itself
            opened += 1
            time.sleep(random.uniform(1.5, 3))
            page = page_get(link)
            if page is not None and page.ok:
                desc = page_text(page.text)[:8000]
        contract = next((c for c in cats if CONTRACT.fullmatch(c.strip())), "") or \
            (m.group(1) if (m := CONTRACT.search(" ".join(lines[1:2]))) else "")
        yield job(id=f"feed:{link}", site=f"feed ({company or urlparse(url).netloc})", title=title, company=firm,
                  location=place, url=link, apply_url=link, posted=_feed_date(text("pubdate") or text("updated")),
                  description=desc) | ({"contract": contract.upper()} if contract else {})


CSP_REF = re.compile(r"^([A-Za-z0-9_][\w./-]*\d[\w./-]*)\s+-\s+(.+)$")  # "MINT_BA067ATB-113461 - Chargé..."


def csp(slug, company, title_ok):
    """Choisir le Service Public's official feeds (one per département, the 20 newest public-sector offers each).
    Items carry the job family, who may apply, the address and the full text; the employer is on the offer page,
    read only for offers whose title passes the filter. Offers reserved to civil servants are marked as such."""
    r = page_get(slug)
    if r is None or not r.ok:
        return
    opened = 0
    for it in _feed_items(r.content):
        link_el, title_el, body = it.find("link"), it.find("title"), it.find("description")
        link = (link_el.get_text(strip=True) or str(link_el.next_sibling or "")).strip() if link_el else ""
        raw = html.unescape(title_el.get_text(" ", strip=True)) if title_el else ""
        m = CSP_REF.match(raw)
        ref, title = (m.group(1), m.group(2).strip()) if m else ("", raw)
        cats = [c.get_text(" ", strip=True) for c in it.find_all("category")]
        open_to = next((c for c in cats if re.search(r"ouvert|r[ée]serv[ée]", c, re.I)), "")
        address = cats[-1] if cats and cats[-1] != open_to else ""
        if not title or not link:
            continue
        firm = ""
        if title_ok(title) and opened < 15:  # the employer, for offers that may reach a candidate
            opened += 1
            time.sleep(random.uniform(1.5, 3))
            page = page_get(link)
            for d in postings_on(page.text) if page is not None and page.ok else []:
                org = d.get("hiringOrganization") or {}
                firm = html.unescape(str(org.get("name") if isinstance(org, dict) else org or "")).strip()
                break
        contractuels = "contractuel" in open_to.lower() or not open_to
        yield job(id=f"csp:{ref}" if ref else f"feed:{link}", site="Choisir le Service Public", title=title,
                  company=firm, location=address, url=link.split("?")[0], apply_url=link.split("?")[0],
                  posted=_feed_date(it.find("pubdate").get_text(strip=True) if it.find("pubdate") else ""),
                  description=text_of(body.get_text()) if body else "") | {
            "source": "Choisir le Service Public",
            "contract": "Contractuel" if "uniquement aux contractuels" in open_to else
                        "Titulaire ou contractuel" if contractuels and open_to else "Titulaire" if open_to else "",
            "contractuels": contractuels}


def rss(slug, company, title_ok):
    """One employer's job feed (Talentsoft career sites publish one: /handlers/offerRss.ashx)."""
    yield from _feed(slug, company, title_ok, multi=False)


def rss_board(slug, company, title_ok):
    """A job board's feed with offers from many employers (Stratégies emploi): the company comes from each offer."""
    yield from _feed(slug, "", title_ok, multi=True)


PROVIDERS = {"lever": lever, "greenhouse": greenhouse, "ashby": ashby, "workable": workable,
             "smartrecruiters": smartrecruiters, "teamtailor": teamtailor, "recruitee": recruitee,
             "personio": personio, "workday": workday, "profilculture": profilculture, "wttj": wttj,
             "rss": rss, "rss_board": rss_board, "csp": csp}


def single_job(url: str) -> dict | None:
    """One posting link on a known ATS, read through its public API (any location)."""
    hit = parse_ats_url(url)
    if not hit:
        return None
    ats, slug = hit
    rest = url.split(slug, 1)[1]
    try:
        if ats == "lever" and (m := re.search(r"/([0-9a-f-]{36})", rest)):
            p = _lever(f"{slug}/{m.group(1)}").json()
            desc = "\n\n".join([p.get("descriptionPlain", ""), *[f"{l.get('text')}\n{text_of(l.get('content'))}"
                                                                 for l in p.get("lists", [])], p.get("additionalPlain", "")])
            return _job("lever", slug, slug.title(), p["id"], p["text"], (p.get("categories") or {}).get("location", ""),
                        p["hostedUrl"], p.get("createdAt"), desc)
        if ats == "greenhouse" and (m := re.search(r"/jobs/(\d+)", rest)):
            p = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{m.group(1)}").json()
            return _job("greenhouse", slug, p.get("company_name") or slug.title(), p["id"], p["title"],
                        (p.get("location") or {}).get("name", ""), p["absolute_url"], p.get("first_published"),
                        text_of(p.get("content")))
        if ats == "smartrecruiters" and (m := re.search(r"/(\d{6,})", rest)):
            d = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{m.group(1)}").json()
            sections = (d.get("jobAd") or {}).get("sections") or {}
            loc = d.get("location") or {}
            return _job("smartrecruiters", slug, (d.get("company") or {}).get("name") or slug, d["id"], d["name"],
                        f"{loc.get('city', '')} {loc.get('country', '')}", d.get("postingUrl") or url, d.get("releasedDate"),
                        "\n\n".join(f"{s.get('title', '')}\n{text_of(s.get('text'))}" for s in sections.values()))
        if ats == "workable" and (m := re.search(r"/j/([0-9A-F]+)", rest, re.I)):
            data = get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true").json()
            p = next(p for p in data.get("jobs", []) if p.get("shortcode", "").upper() == m.group(1).upper())
            return _job("workable", slug, data.get("name") or slug, p["shortcode"], p["title"],
                        f"{p.get('city', '')} {p.get('country', '')}", p.get("url") or url, p.get("published_on"),
                        text_of(p.get("description")))
    except Exception as e:
        log.info("ATS lookup failed for %s: %s", url, e)
    return None


# schema.org JobPosting (custom career sites) ------------------------------------------------------

def postings_on(page_html: str) -> list[dict]:
    soup = BeautifulSoup(page_html, "html.parser")
    found = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                if d.get("@type") == "JobPosting" or "JobPosting" in (d.get("@type") or []):
                    found.append(d)
                stack += [v for k, v in d.items() if k in ("@graph", "itemListElement", "item")]
            elif isinstance(d, list):
                stack += d
    return found


def from_posting(d: dict, url: str, source: str) -> dict:
    org = d.get("hiringOrganization") or {}
    locs = d.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    places = []
    for l in locs:
        addr = (l.get("address") or {}) if isinstance(l, dict) else {}
        if isinstance(addr, dict):  # skip schema keys like "@type": "PostalAddress"
            places.append(", ".join(v for k, v in addr.items() if isinstance(v, str) and v.strip() and not k.startswith("@")))
        elif isinstance(addr, str):
            places.append(addr)
    where = " / ".join(p for p in places if p)
    if d.get("jobLocationType") == "TELECOMMUTE":
        where += " remote " + " ".join(str(a.get("name", "")) for a in (d.get("applicantLocationRequirements") or [])
                                       if isinstance(a, dict))
    title = html.unescape(str(d.get("title") or "")).strip()
    company = html.unescape(str((org.get("name") if isinstance(org, dict) else org) or ""))
    link = d.get("url") or url
    return job(id=f"jsonld:{link}#{slug(title, 60)}", site=source, title=title, company=company, location=where,
               url=link, apply_url=link, posted=str(d.get("datePosted") or "")[:10], description=text_of(d.get("description")))


JOB_LINK = re.compile(r"job|career|carriere|offre|emploi|poste|recrut|vacanc|position|opening|join", re.I)


def jsonld(url, company, title_ok, max_pages: int = 25, seen=None):
    """A careers page: JobPosting data on the page itself, or on the job pages it links to.
    seen(url) -> True skips job pages read on an earlier poll, so the page budget goes to new ones."""
    r = page_get(url)
    if r is None or not r.ok:
        return
    direct = postings_on(r.text)
    for d in direct:
        j = from_posting(d, url, "career page")
        j["company"] = j["company"] or company
        if title_ok(j["title"]) and in_area(j["location"], empty=True):
            yield j
    if direct:
        return
    host = urlparse(r.url).netloc
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(r.url, a["href"]).split("#")[0]
        if (urlparse(href).netloc == host and href != r.url and JOB_LINK.search(href) and title_ok(a.get_text(" "))
                and not (seen and seen(href))):
            links.append(href)
    # Deepest paths first: job pages (/emplois/seo/egym/senior-seo-manager) before category pages (/emplois/seo).
    links = sorted(dict.fromkeys(links), key=lambda h: -urlparse(h).path.rstrip("/").count("/"))
    for href in links[:max_pages]:
        time.sleep(random.uniform(1, 2.5))
        page = page_get(href)
        for d in postings_on(page.text) if page is not None and page.ok else []:
            j = from_posting(d, href, "career page")
            j["company"] = j["company"] or company
            if in_area(j["location"], empty=True):
                yield j


# watchlist --------------------------------------------------------------------------------------

BOARD_PAGES = {"lever": "https://jobs.lever.co/{}", "ashby": "https://jobs.ashbyhq.com/{}",
               "recruitee": "https://{}.recruitee.com", "personio": "https://{}.jobs.personio.de"}


def board_name(ats: str, slug: str, url: str = "") -> str:
    """The company name the board itself shows: 'Groupe Galeries Lafayette', not 'Groupegalerieslafayette'."""
    try:
        if ats == "greenhouse":
            name = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}").json().get("name")
        elif ats == "workable":
            name = get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}").json().get("name")
        elif ats == "smartrecruiters":
            hits = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1").json().get("content")
            name = ((hits or [{}])[0].get("company") or {}).get("name")
        elif ats == "teamtailor":
            name = ET.fromstring(get(f"https://{_tt_host(slug)}/jobs.rss").content).findtext("channel/title")
        else:  # the board page's own title
            page = BOARD_PAGES[ats].replace("jobs.lever", "jobs.eu.lever" if "eu.lever" in url else "jobs.lever")
            r = get(page.format(slug))
            if r is None or not r.ok:  # an error page's title is not a company name
                return ""
            soup = BeautifulSoup(r.text, "html.parser")
            og = soup.find("meta", property="og:site_name")
            name = (og.get("content") if og else "") or (soup.title.get_text() if soup.title else "")
    except Exception:
        return ""
    return clean_name(name or "")


def clean_name(name: str) -> str:
    """'Offres d'emploi disponibles - Groupe Galeries Lafayette' -> 'Groupe Galeries Lafayette'."""
    name = re.sub(r"^(jobs|careers|carri[eè]res|offres d.emploi[^-–|]*?)\s*(at|chez|[-–|])\s*|"
                  r"\s*[-–|]?\s*\b(jobs|careers|carri[eè]res|emplois?|recrutement)$", "", name.strip(), flags=re.I)
    name = re.sub(r"\s+(SAS|SASU|SA|SARL|GmbH|Inc\.?|Ltd\.?|LLC|BV|AG)$", "", name.strip(" -–|"))
    if name.isupper() and len(name) > 5:  # 'JACQUEMUS' -> 'Jacquemus', 'BETC' stays
        name = name.title()
    return name[:1].upper() + name[1:]  # 'lemlist' -> 'Lemlist': a lowercase name reads as a typo on a CV


def is_teamtailor(host: str) -> bool:
    """Many French career sites (careers.shine.co, careers.ornikar.com...) are Teamtailor boards on their own
    domain. Their feed lists every job, where a discovered link to one posting would go stale."""
    r = get(f"https://{host}/jobs.rss")
    return r is not None and r.ok and b"teamtailor.com" in r.content[:600]


def add_url(store, url: str, name: str = "", source: str = "manual") -> str | None:
    """Add a career page (ATS board or any careers URL) to the watchlist."""
    hit = parse_ats_url(url)
    if hit:
        ats, slug = hit
        if store.has_company(f"{ats}:{slug.lower()}"):
            return None
        fallback = slug.split(".")[0] if ats == "workday" else slug  # "relx.wd3/relx" -> "Relx", not "Relx.Wd3/Relx"
        pretty = name or board_name(ats, slug, url) or fallback.replace("-", " ").replace("_", " ").title()
        added = store.add_company(f"{ats}:{slug.lower()}", pretty, ats, slug, url, source)
        return f"{ats}:{slug}" if added else None
    site = site_source(url)
    if site or re.search(r"offerRss\.ashx|/rss/?$|\.rss$|/feed/?$", url, re.I):
        key, kind, address = site or (f"rss:{url}", "rss", url)
        added = store.add_company(key, name or urlparse(address).netloc, kind, address if kind == "rss" else "",
                                  address, source)
        return address if added else None
    host = urlparse(url).netloc.lower()
    if urlparse(url).scheme in ("http", "https") and not any(b in host for b in JOB_BOARDS):
        if store.has_company(f"teamtailor:{host}") or store.has_company(f"jsonld:{url}"):
            return None
        if is_teamtailor(host):
            added = store.add_company(f"teamtailor:{host}", name or board_name("teamtailor", host) or host,
                                      "teamtailor", host, f"https://{host}/jobs", source)
            return host if added else None
        added = store.add_company(f"jsonld:{url}", name or host, "jsonld", "", url, source)
        return url if added else None
    return None


# French career-site platforms read without an API: Talentsoft sites publish a job feed, nous-recrutons.fr sites
# carry schema.org JobPosting data on every offer and list them on their home page.
SITE_PLATFORMS = [
    (re.compile(r"https?://([a-z0-9-]+)\.talent-soft\.com", re.I), "rss",
     "https://{}.talent-soft.com/handlers/offerRss.ashx?LCID=1036"),
    (re.compile(r"https?://([a-z0-9-]+)\.nous-recrutons\.fr", re.I), "jsonld", "https://{}.nous-recrutons.fr/"),
]


def site_source(url: str) -> tuple[str, str, str] | None:
    """(watchlist key, kind, address to read) for a career site on a platform read through a feed or its pages."""
    for pattern, kind, template in SITE_PLATFORMS:
        if m := pattern.search(url or ""):
            address = template.format(m.group(1).lower())
            return f"{kind}:{address}", kind, address
    return None


def learn(store, jobs: list[dict]) -> int:
    """Board postings often link straight to the company ATS or career site: remember those."""
    n = 0
    for j in jobs:
        for url in (j.get("apply_url"), j.get("company_url"), j.get("url")):
            hit = parse_ats_url(url or "")
            if hit and store.add_company(f"{hit[0]}:{hit[1].lower()}", j["company"] or hit[1], hit[0], hit[1],
                                         url, "seen on a job board"):
                n += 1
            site = site_source(url or "")
            if site and store.add_company(site[0], j["company"] or urlparse(site[2]).netloc, site[1],
                                          site[2] if site[1] == "rss" else "", site[2], "seen on a job board"):
                n += 1
    return n


def _slug_guesses(name: str) -> list[str]:
    base = re.sub(r"\b(sas|sa|sarl|group|groupe|france|paris|inc|ltd|gmbh|the)\b", " ", fold(name)).split()
    if not base:
        return []
    return list(dict.fromkeys(["".join(base), "-".join(base), base[0]]))[:3]


def probe(store, name: str) -> str | None:
    """Look for a company's job board on each ATS by guessing its slug. Remembered either way."""
    key = f"probed:{fold(name).strip()}"
    if not name or store.has_company(key):
        return None
    store.add_company(key, name, "none", "", "", "probe", active=False)
    for guess in _slug_guesses(name):
        for ats in ("lever", "greenhouse", "ashby", "workable", "teamtailor", "recruitee"):
            url = {"lever": f"https://api.lever.co/v0/postings/{guess}?mode=json",
                   "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{guess}/jobs",
                   "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{guess}",
                   "workable": f"https://apply.workable.com/api/v1/widget/accounts/{guess}",
                   "teamtailor": f"https://{guess}.teamtailor.com/jobs.rss",
                   "recruitee": f"https://{guess}.recruitee.com/api/offers/"}[ats]
            r = get(url)
            if r is not None and r.ok and _has_jobs(ats, r) and _same_company(ats, r, name):
                store.add_company(f"{ats}:{guess}", name, ats, guess, url, "probe")
                return f"{ats}:{guess}"
        r = get(f"https://api.smartrecruiters.com/v1/companies/{guess}/postings?limit=1")
        if r is not None and r.ok and r.json().get("totalFound"):
            store.add_company(f"smartrecruiters:{guess}", name, "smartrecruiters", guess, "", "probe")
            return f"smartrecruiters:{guess}"
    return None


def _has_jobs(ats: str, r: requests.Response) -> bool:
    try:
        if ats in ("teamtailor",):
            return b"<item>" in r.content
        d = r.json()
        return bool(d if isinstance(d, list) else d.get("jobs") or d.get("offers"))
    except ValueError:
        return False


def _same_company(ats: str, r: requests.Response, name: str) -> bool:
    """Guard against another company owning the same slug, where the board says who it belongs to."""
    try:
        d = r.json()
    except ValueError:
        return True
    owner = (d.get("name") if isinstance(d, dict) else "") or ""
    if not owner and isinstance(d, dict) and d.get("jobs"):
        owner = d["jobs"][0].get("company_name") or ""
    return not owner or fold(name).split()[0] in fold(owner)


# Boards whose listing already carries every posting's full text: with an archive, all their jobs in France are
# kept, whatever the title. The other kinds open one page per job, so only titles that pass the filter are opened.
WHOLE_LISTING = {"lever", "greenhouse", "ashby", "workable", "teamtailor", "recruitee", "personio", "rss", "rss_board",
                 "csp"}


def poll(store, cfg: dict, title_ok, keep=None, workers: int = 16) -> list[dict]:
    """Fetch due career pages and return fresh France-based postings that pass the title filter.
    keep(jobs): receives every fresh posting found, whatever its title (the national archive).
    Each platform (Greenhouse, Workday, the public-sector feeds...) is read in its own thread, one board after the
    other with a pause, so a big watchlist takes about as long as its biggest platform."""
    from concurrent.futures import ThreadPoolExecutor

    global COUNTRY, HOME
    COUNTRY, HOME = targets.country(cfg), targets.home_city(cfg)
    cp = cfg["career_pages"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=cp["max_age_days"])).date().isoformat()
    read_before = {r[0] for r in store.db.execute("select url from jobs")}  # threads cannot share the store
    seen = read_before.__contains__
    groups: dict[str, list] = {}
    for c in store.companies_due(cp["poll_every_hours"]):
        if c["ats"] == "jsonld" or c["ats"] in PROVIDERS:
            groups.setdefault(c["ats"], []).append(c)

    deadline = time.time() + cp.get("max_minutes_per_run", 15) * 60  # one deadline for every platform

    def read(companies: list) -> list[tuple]:
        """One platform's boards, the least recently polled first, until the run's time budget is used: the rest
        stay due and come first next run, so a watchlist of thousands never stretches a run (a platform that waited
        for a free thread gets no extra time)."""
        results = []
        for c in companies:
            if time.time() > deadline:
                break
            fn = jsonld if c["ats"] == "jsonld" else PROVIDERS[c["ats"]]
            try:
                if c["ats"] == "jsonld":
                    found = list(fn(c["url"], c["name"], title_ok, seen=seen))
                elif c["ats"] == "wttj":  # opens one page per offer: skip the offers already read
                    found = list(fn(c["slug"], c["name"], title_ok, seen=seen))
                elif keep and c["ats"] in WHOLE_LISTING:
                    found = list(fn(c["slug"], c["name"], lambda title: True))
                else:
                    found = list(fn(c["slug"], c["name"], title_ok))
            except Exception as e:
                log.info("career page %s failed: %s", c["key"], e)
                found = []
            results.append((c, found))
            time.sleep(random.uniform(0.3, 1.0))
        return results

    out = []
    with ThreadPoolExecutor(max(1, min(workers, len(groups)))) as pool:
        for results in pool.map(read, groups.values()):
            for c, found in results:  # the store and the archive are written here, in the caller's thread
                fresh = [j for j in found if not j["posted"] or j["posted"] >= cutoff]
                if keep and fresh:
                    keep(fresh)
                matching = [j for j in fresh if title_ok(j["title"])  # posts for civil servants only are not for
                            and j.get("contractuels", True) is not False]  # candidates
                store.mark_polled(c["key"], len(matching))
                out += matching
    log.info("career pages: %d matching postings", len(out))
    return out

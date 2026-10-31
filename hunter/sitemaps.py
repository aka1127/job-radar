"""Job sites that list every offer in a sitemap and allow crawling it (robots.txt): new offers are read one page at a
time, politely, by a background thread, into the national archive. The candidates' runs then match from there."""
import logging
import random
import re
import threading
import time

from . import careers
from .archive import Archive

log = logging.getLogger(__name__)
# name: the source name in the archive; sitemap: the list of offer pages; offer: the offer number in an address.
SITES = [
    {"name": "jobposting.pro", "sitemap": "https://www.jobposting.pro/sitemap-offres.xml",
     "offer": re.compile(r"/emploi-(\d+)-\d+/?$")},
    # Jobs that make sense: impact jobs (NGOs, social economy); each offer is listed in French and English: French only
    {"name": "Jobs that make sense", "sitemap": "https://jobs.makesense.org/sitemap-jobs.xml",
     "offer": re.compile(r"/fr/jobs/.+-([A-Za-z0-9]{12,})/?$")},
]
CAUGHT_UP_PAUSE = 30 * 60  # once every offer is read, look at the sitemap again half an hour later


def offer_urls(site: dict) -> list[str]:
    """Offer pages listed in the sitemap, newest first (the order the site gives)."""
    r = careers.page_get(site["sitemap"])
    if r is None or not r.ok:
        return []
    return [u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text) if site["offer"].search(u)]


def offer_id(site: dict, url: str) -> str:
    return f"{site['name']}:{site['offer'].search(url).group(1)}"


def read_offer(site: dict, url: str) -> dict | None:
    page = careers.page_get(url)
    if page is None or not page.ok:
        return None
    for d in careers.postings_on(page.text):
        j = careers.from_posting(d, url, site["name"])
        if j["title"]:
            return j | {"id": offer_id(site, url), "source": site["name"], "url": url, "apply_url": url}
    return None


def crawl(arch: Archive, site: dict, stop: threading.Event | None = None, budget_s: float = 3600,
          pause: tuple[float, float] = (1.5, 3.0)) -> int:
    """Read the offers of one site that the archive does not hold yet, for at most budget_s seconds."""
    urls = offer_urls(site)
    known = {r[0] for r in arch.db.execute("select id from postings where source=?", (site["name"],))}
    todo = [u for u in urls if offer_id(site, u) not in known]
    started, saved, read = time.time(), 0, 0
    for url in todo:
        if (stop and stop.is_set()) or time.time() - started > budget_s:
            break
        time.sleep(random.uniform(*pause))
        read += 1
        j = read_offer(site, url)
        if j:
            saved += arch.save([j])
    log.info("%s: %d new offers archived (%d left to read)", site["name"], saved, len(todo) - read)
    return saved


def harvest_forever(stop: threading.Event):
    """Background thread of the loop: keeps every sitemap site read, an hour of reading per site per turn."""
    from . import opendata

    arch = Archive()  # its own connection: SQLite connections stay in their thread
    while not stop.is_set():
        new = 0
        try:  # the State's public-sector offers file, when data.gouv.fr has a new version (checked once a day)
            new += opendata.import_due(arch)
        except Exception as e:
            log.warning("open data import failed: %s", careers_error(e))
        for site in SITES:
            try:
                new += crawl(arch, site, stop)
            except Exception as e:  # a site down must never stop the others or the loop
                log.warning("%s crawl failed: %s", site["name"], careers_error(e))
        stop.wait(CAUGHT_UP_PAUSE if new == 0 else 5)


def careers_error(e: Exception) -> str:
    return (str(e).strip().splitlines() or [""])[0][:200]

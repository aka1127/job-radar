"""France Travail national harvest: every offer published in France, all jobs, all cities, into the archive.
The API returns at most 1,150 results per query, 150 per page: a time slice holding more is cut in two until each
fits, so nothing is left out. It runs only once the application has access to the "Offres d'emploi v2" API."""
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from .sources import FranceTravail

log = logging.getLogger(__name__)
PAGE, WINDOW, LAST_START = 150, 1150, 1000  # page size, results per query, highest first index the API accepts
FMT = "%Y-%m-%dT%H:%M:%SZ"
DETAIL = "https://candidat.francetravail.fr/offres/recherche/detail/"


def ranges(total: int) -> list[tuple[int, int]]:
    """Pages covering min(total, 1150) results: 0-149, 150-299, ..., 900-1049, then 1000-1149."""
    out, start = [], 0
    while start < min(total, WINDOW):
        start = min(start, LAST_START)
        end = min(start + PAGE, WINDOW) - 1
        out.append((start, end))
        if end >= WINDOW - 1:
            break
        start = end + 1
    return out


def posting(o: dict) -> dict:
    """One API offer as an archive row, with the fields a job database needs (contract, ROME code, salary...)."""
    place, firm, origin = o.get("lieuTravail") or {}, o.get("entreprise") or {}, o.get("origineOffre") or {}
    url = origin.get("urlOrigine") or DETAIL + str(o["id"])
    extra = {"rome_label": o.get("romeLibelle"), "job_label": o.get("appellationlibelle"),
             "contract_label": o.get("typeContratLibelle"), "salary": (o.get("salaire") or {}).get("libelle"),
             "experience": o.get("experienceLibelle"), "qualification": o.get("qualificationLibelle"),
             "sector": o.get("secteurActiviteLibelle"), "hours": o.get("dureeTravailLibelle"),
             "positions": o.get("nombrePostes"), "company_url": firm.get("url"), "insee": place.get("commune"),
             "partners": [p.get("nom") for p in origin.get("partenaires") or [] if p.get("nom")]}
    return {"id": f"france_travail:{o['id']}", "site": "france_travail", "source": "France Travail",
            "title": o.get("intitule") or "", "company": firm.get("nom") or "", "location": place.get("libelle") or "",
            "postcode": place.get("codePostal") or place.get("commune") or "", "contract": o.get("typeContrat") or "",
            "rome": o.get("romeCode") or "", "posted": (o.get("dateCreation") or "")[:10], "url": url,
            "apply_url": origin.get("urlOrigine") or "", "description": o.get("description") or "",
            "extra": {k: v for k, v in extra.items() if v not in (None, "", [])}}


class Harvester:
    def __init__(self, ft: FranceTravail, archive, pause: float = 0.15):
        self.ft, self.archive, self.pause = ft, archive, pause  # 0.15 s keeps well under the 10 calls/s quota

    def _page(self, since: datetime, until: datetime, start: int, end: int) -> tuple[list[dict], int]:
        params = {"minCreationDate": since.strftime(FMT), "maxCreationDate": until.strftime(FMT),
                  "range": f"{start}-{end}"}
        for attempt in range(5):
            time.sleep(self.pause)
            r = requests.get(FranceTravail.SEARCH_URL, params=params, headers=self.ft.headers(), timeout=60)
            if r.status_code == 204:
                return [], 0
            if r.status_code == 401:  # token expired early
                self.ft.reset()
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(float(r.headers.get("Retry-After") or 2 * (attempt + 1)))
                continue
            r.raise_for_status()
            offers = r.json().get("resultats") or []
            m = re.search(r"/(\d+)", r.headers.get("Content-Range", ""))
            return offers, int(m.group(1)) if m else len(offers)
        raise RuntimeError(f"France Travail kept refusing {params}")

    def slice(self, since: datetime, until: datetime) -> int:
        """Every offer created in [since, until]; returns how many were new to the archive."""
        offers, total = self._page(since, until, 0, PAGE - 1)
        if total > WINDOW and until - since > timedelta(minutes=2):
            middle = since + (until - since) / 2
            return self.slice(since, middle) + self.slice(middle, until)
        new = self.archive.save([posting(o) for o in offers])
        for start, end in ranges(total)[1:]:
            offers, _ = self._page(since, until, start, end)
            new += self.archive.save([posting(o) for o in offers])
        return new

    def run(self, since: datetime, until: datetime | None = None, step: timedelta = timedelta(hours=6)) -> int:
        """Walk from since to until in steps (each step split further when it holds over 1,150 offers)."""
        until = until or datetime.now(timezone.utc) - timedelta(minutes=5)
        new, t = 0, since
        while t < until:
            nxt = min(t + step, until)
            new += self.slice(t, nxt)
            self.archive.put("ft_harvest_until", nxt.strftime(FMT))
            t = nxt
        return new


def harvest_due(archive, ft: FranceTravail | None = None, first_days: int = 1) -> int:
    """Called every cycle: everything published since the last harvest (the last day on the first run)."""
    ft = ft or FranceTravail()
    if not ft.enabled:
        return 0
    last = archive.get("ft_harvest_until")
    since = (datetime.strptime(last, FMT).replace(tzinfo=timezone.utc) if last
             else datetime.now(timezone.utc) - timedelta(days=first_days))
    try:
        new = Harvester(ft, archive).run(since)
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code in (400, 401, 403):  # no access to Offres d'emploi v2 yet (France Travail grants it on request)
            log.info("France Travail harvest: no access to the Offres d'emploi API yet (HTTP %s)", code)
            return 0
        raise
    log.info("France Travail harvest: %d new offers since %s", new, since.strftime("%d/%m %H:%M"))
    return new

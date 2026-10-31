"""Discover company job boards with jobs in France from public lists of ATS boards (for example the MIT-licensed
lists of github.com/Riley-Dorrington/job-board-aggregator: data/<ats>_companies.json). Each board is checked once
through the public job API its platform offers for that purpose, a few at a time per platform; boards with at least
one job in France join the watchlist (their postings then flow into the archive at every poll)."""
import csv
import json
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import careers

log = logging.getLogger(__name__)
HEADERS = careers.UA | {"Accept": "application/json"}


def _get_json(url: str, **kw):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, **kw)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def greenhouse(slug: str) -> int:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    return sum(careers.in_france((j.get("location") or {}).get("name") or "") for j in (data or {}).get("jobs", []))


def lever(slug: str) -> int:
    r = careers._lever(f"{slug}?mode=json")  # tries the EU host too
    try:
        jobs = r.json() if r is not None and r.ok else []
    except ValueError:
        jobs = []
    return sum(careers.in_france(" ".join(filter(None, [(p.get("categories") or {}).get("location") or "",
                                                        p.get("country") or ""]))) for p in jobs if isinstance(p, dict))


def ashby(slug: str) -> int:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    n = 0
    for j in (data or {}).get("jobs", []):
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        where = " ".join(filter(None, [j.get("location") or "", addr.get("addressLocality") or "",
                                       addr.get("addressCountry") or ""]))
        n += careers.in_france(where)
    return n


def workday(entry: str) -> int:
    """entry: 'tenant|wdN|site' as in the lists."""
    tenant, cluster, site = (entry.split("|") + ["", "", ""])[:3]
    if not (tenant and cluster and site):
        return 0
    try:
        r = requests.post(f"https://{tenant}.{cluster}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                          json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "France"},
                          headers=HEADERS | {"Content-Type": "application/json"}, timeout=20)
        data = r.json() if r.ok else {}
    except (requests.RequestException, ValueError):
        return 0
    return sum(careers.in_france(p.get("locationsText") or "") for p in data.get("jobPostings") or [])


PROBES = {"greenhouse": (greenhouse, 4), "lever": (lever, 3), "ashby": (ashby, 3), "workday": (workday, 4)}


def slug_and_url(ats: str, entry: str) -> tuple[str, str]:
    if ats == "workday":
        tenant, cluster, site = entry.split("|")[:3]
        return f"{tenant}.{cluster}/{site}", f"https://{tenant}.{cluster}.myworkdayjobs.com/{site}"
    return entry, {"greenhouse": f"https://job-boards.greenhouse.io/{entry}", "lever": f"https://jobs.lever.co/{entry}",
                   "ashby": f"https://jobs.ashbyhq.com/{entry}"}[ats]


LISTS = "https://raw.githubusercontent.com/Riley-Dorrington/job-board-aggregator/main/data/{}_companies.json"


def fetch_lists(folder: Path) -> list[str]:
    """The latest public board lists (MIT licence, refreshed daily by their author), saved in folder."""
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for ats in PROBES:
        try:
            r = requests.get(LISTS.format(ats), timeout=60)
            if r.ok and r.text.lstrip().startswith("["):
                (folder / f"{ats}_companies.json").write_text(r.text, encoding="utf-8")
                saved.append(ats)
        except requests.RequestException as e:
            log.warning("board list %s not fetched: %s", ats, e)
    return saved


def discover(store, lists: Path, report: Path | None = None, limit: int | None = None,
             pause: tuple[float, float] = (0.15, 0.4)) -> dict[str, int]:
    """Check every board of every list once; add the ones with jobs in France. Returns boards added per platform."""
    known = {r["key"] for r in store.db.execute("select key from companies")}
    found: list[tuple[str, str, int]] = []
    lock = threading.Lock()

    def run(ats: str, entries: list[str], workers: int):
        probe = PROBES[ats][0]
        done = 0

        def one(entry: str):
            nonlocal done
            time.sleep(random.uniform(*pause))
            n = probe(entry)
            with lock:
                done += 1
                if n:
                    found.append((ats, entry, n))
                if done % 500 == 0:
                    log.info("%s: %d/%d boards checked, %d with jobs in France", ats, done, len(entries),
                             sum(1 for a, _, _ in found if a == ats))
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(one, entries))

    plans = []
    for ats, (probe, workers) in PROBES.items():
        path = lists / f"{ats}_companies.json"
        if not path.exists():
            continue
        entries = [e for e in json.loads(path.read_text(encoding="utf-8")) if isinstance(e, str)]
        entries = [e for e in entries if f"{ats}:{slug_and_url(ats, e)[0].lower()}" not in known][:limit]
        plans.append((ats, entries, workers))
    with ThreadPoolExecutor(len(plans) or 1) as pool:  # the platforms side by side, each at its own pace
        list(pool.map(lambda p: run(*p), plans))

    added: dict[str, int] = {}
    for ats, entry, n in sorted(found, key=lambda f: -f[2]):
        slug, url = slug_and_url(ats, entry)
        name = (careers.board_name(ats, slug, url) if ats in ("greenhouse",) else "") or \
            slug.split(".")[0].replace("-", " ").replace("_", " ").title()
        if store.add_company(f"{ats}:{slug.lower()}", name, ats, slug, url, "github list (job-board-aggregator)"):
            added[ats] = added.get(ats, 0) + 1
    if report:
        with open(report, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ats", "board", "jobs_in_france"])
            w.writerows(sorted(found, key=lambda f: -f[2]))
    log.info("board discovery: %s added (%d boards with jobs in France)", added, len(found))
    return added

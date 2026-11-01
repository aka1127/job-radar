"""Job alert emails as a source. Welcome to the Jungle, APEC, LinkedIn and other boards email their alerts to a
mailbox; the engine reads it over IMAP and turns every job link into a full posting. This covers boards that
cannot be searched directly, and brings LinkedIn jobs without touching its rate-limited search pages.

Setup in .env (an app password, never the account password): ALERTS_IMAP_USER, ALERTS_IMAP_PASSWORD, optional
ALERTS_IMAP_HOST (default imap.gmail.com) and ALERTS_IMAP_FOLDER (default INBOX; a Gmail label works).
Add _<NAME> to a key for one candidate only (ALERTS_IMAP_USER_ALEX)."""
import base64
import binascii
import email
import imaplib
import logging
import re
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from . import careers, geo, sources, targets
from .web import UA

log = logging.getLogger(__name__)
SENDERS = re.compile(r"welcometothejungle|wttj|apec\.fr|linkedin\.com|hellowork|indeed|cadremploi|jobteaser|"
                     r"meteojob|glassdoor|francetravail|monster|talent\.io|jobsthatmakesense", re.I)
JOB_LINKS = {
    "wttj": re.compile(r"https://www\.welcometothejungle\.com/[a-z]{2}/companies/[^/\s\"'<>]+/jobs/[^\s\"'<>?#]+"),
    "linkedin": re.compile(r"https://(?:[a-z]{2,3}\.|www\.)?linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#\s\"'<>]*?-)?(\d{6,})"),
    "apec": re.compile(r"https://www\.apec\.fr/candidat/recherche-emploi\.html/emploi/detail-offre/[\w-]+"),
    "cadremploi": re.compile(r"https://www\.cadremploi\.fr/emploi/detail_offre\?(?:[^\s\"'<>#]*&)?offreId=(\d+)"),
    "hellowork": re.compile(r"https://www\.hellowork\.com/fr-fr/emplois/(\d+)\.html"),
    "meteojob": re.compile(r"https://(?:www\.)?meteojob\.com/jobs/(\d+)"),
    # Indeed: the country site the alert links to (fr.indeed.com, de.indeed.com, www.indeed.com...) is kept
    "indeed": re.compile(r"https://((?:[a-z]{2}\.|www\.)?indeed\.(?:com|[a-z]{2}))/[^\s\"'<>]*?[?&]jk=([0-9a-f]{16})"),
}
CANONICAL = {"linkedin": "https://www.linkedin.com/jobs/view/{}",
             "cadremploi": "https://www.cadremploi.fr/emploi/detail_offre?offreId={}",
             "hellowork": "https://www.hellowork.com/fr-fr/emplois/{}.html", "meteojob": "https://www.meteojob.com/jobs/{}",
             "indeed": "https://{}/viewjob?jk={}"}
TRACKER = re.compile(r"(^|\.)(click|clicks|links?|email|emails|e|t|trk|track|tracking|mail|mailing|news)\.|sendgrid|"
                     r"mailchimp|list-manage|/ls/click|/c/|redirect", re.I)
MAX_RESOLVE = 150  # tracking links followed per run (a morning brings a dozen alert emails)
# Offer pages that refuse automated visits: APEC and Cadremploi answer 403, Indeed's robots.txt forbids them.
# Their alert emails carry the offer itself (title, company, place, contract, summary): read it there.
BLOCKS_BOTS = {"apec", "cadremploi", "indeed"}
APEC_OFFER = "https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/"


def apec_offer(url: str) -> str | None:
    """APEC alert links are tracking redirects (diffusion.apec.fr/r/?id=...&e=...) whose `e` parameter is base64 for
    "p1=www.apec.fr&p2=<offer number>". Offer numbers end in W; plain numbers are "see all offers" searches."""
    if "apec.fr" not in url:
        return None
    e = (parse_qs(urlparse(url).query).get("e") or [""])[0].replace(" ", "+")  # a raw "+" arrives as a space
    for decode in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            text = unquote(decode(e + "=" * (-len(e) % 4)).decode("utf-8", "replace"))
        except (ValueError, binascii.Error):
            continue
        m = re.search(r"(?:^|&)p2=(\d{6,}W)(?:&|$)", text)
        if m:
            return APEC_OFFER + m.group(1)
    return None


def _offer_key(url: str) -> str:
    """Links to the same offer (its title, company, contract and place are often separate links) share one key."""
    hit = job_link(url)
    return hit[1] if hit else url


def enabled(cand) -> bool:
    return bool(cand.env("ALERTS_IMAP_USER") and cand.env("ALERTS_IMAP_PASSWORD"))


def _connect(cand) -> imaplib.IMAP4_SSL:
    box = imaplib.IMAP4_SSL(cand.env("ALERTS_IMAP_HOST") or "imap.gmail.com", timeout=60)
    box.login(cand.env("ALERTS_IMAP_USER").strip(), cand.env("ALERTS_IMAP_PASSWORD").replace(" ", ""))  # Google shows it in 4 blocks
    box.select(f'"{cand.env("ALERTS_IMAP_FOLDER") or "INBOX"}"', readonly=True)  # never marks alerts as read
    return box


def _block(anchor) -> list[str]:
    """The offer's own block in an alert email: from its link up to the largest element that holds no other
    offer (another link with a title-like text), as text lines."""
    key, best, node = _offer_key(anchor.get("href", "")), anchor, anchor
    while node.parent is not None and node.parent.name not in ("body", "html", "[document]"):
        node = node.parent
        others = [a for a in node.find_all("a", href=True)
                  if _offer_key(a["href"]) != key and len(a.get_text(" ", strip=True)) >= 12
                  and not NOISE.search(a.get_text())]
        if others or len(node.get_text(" ", strip=True)) > 900:
            break
        best = node
    return [l for l in best.get_text("\n", strip=True).splitlines() if l.strip()]


def links_in(message: email.message.Message) -> list[tuple[str, str, list[str]]]:
    """(link, its text, the offer block around it) for every link in the email, HTML preferred."""
    parts = {p.get_content_type(): p for p in message.walk() if p.get_content_type() in ("text/html", "text/plain")}
    part = parts.get("text/html") or parts.get("text/plain")
    if part is None:
        return []
    body = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="replace")
    if part.get_content_type() == "text/plain":
        return [(u, "", []) for u in dict.fromkeys(re.findall(r"https?://[^\s\"'<>]+", body))]
    soup = BeautifulSoup(body, "html.parser")
    return [(a["href"].strip(), a.get_text(" ", strip=True), _block(a)) for a in soup.find_all("a", href=True)
            if a["href"].startswith("http")]


NOISE = re.compile(r"^\s*(voir( l.offre| plus)?|postuler|candidater|d[ée]couvrir|en savoir plus|se d[ée]sinscrire|"
                   r"d[ée]sinscription|g[ée]rer (mes|vos) alertes|modifier|nouvelles? offres?|apec|view|apply|see more)\b",
                   re.I)
PLACE = re.compile(r"\s-\s\d{2}\b|\(\d{2}\)|\b(Paris|[ÎI]le-de-France|France|Lyon|Marseille|Lille|Bordeaux|Toulouse|"
                   r"Nantes|Nice|Rennes|Strasbourg|Montpellier|La D[ée]fense|Boulogne|Levallois|Neuilly|Issy|Nanterre)\b")
DEPARTMENT = re.compile(r"\s-\s(\d{2,3}|2[AB])\s*$|\(\d{2}\)\s*$")
DETAIL = re.compile(r"\b(CDI|CDD|Int[ée]rim|Alternance|Stage|Freelance)\b|k€|€|brut|salaire|exp[ée]rience|il y a|publi",
                    re.I)


def from_block(board: str, url: str, title: str, lines: list[str], posted: str, country: str = "FR") -> dict | None:
    """Boards that refuse automated visits (APEC answers 403) still put the offer in the alert itself: title,
    company, place, contract, salary and a summary. That block becomes the posting. country: the candidate's, the
    place when the block names none (alerts are set up for that country)."""
    lines = [l for l in lines if not NOISE.search(l)]
    title = title if len(title) >= 8 and not NOISE.search(title) else (lines[0] if lines else "")
    rest = [l for l in lines if l != title]
    short = [l for l in rest if len(l) <= 60]
    # "Lyon 01 - 69" (city - department) beats a company name that merely contains "France"; elsewhere any short
    # line that names a place of the country ("Berlin", "München, Bayern").
    place = (next((l for l in short if DEPARTMENT.search(l)), "") or next((l for l in short if PLACE.search(l)), "")
             or next((l for l in short if not DETAIL.search(l) and geo.in_country(l, country)), ""))
    company = next((l for l in short if l != place and not DETAIL.search(l)), "")
    if not title or not rest:
        return None
    description = "\n".join([title, *rest, "", "(Summary from the job alert email; the full posting is on the link.)"])
    return sources.job(id=f"alert:{url}", site=f"email alert ({board})", title=title, company=company,
                       location=place or geo.country_name(country), url=url, apply_url=url, posted=posted,
                       description=description) | {"summary_only": True}


def job_link(url: str) -> tuple[str, str] | None:
    """('wttj', canonical url) for a link that points at one job, else None."""
    offer = apec_offer(url)
    if offer:
        return "apec", offer
    for text in dict.fromkeys((url, unquote(url))):  # the offer link may sit encoded inside a tracking link
        for board, pattern in JOB_LINKS.items():
            m = pattern.search(text)
            if m:
                return board, (CANONICAL[board].format(*m.groups()) if board in CANONICAL else m.group(0))
    return None


def _resolve(url: str) -> str:
    """Where a tracking link lands, without downloading the page."""
    try:
        r = requests.get(url, headers=UA, timeout=15, allow_redirects=True, stream=True)
        r.close()
        return r.url
    except requests.RequestException:
        return ""


def to_job(board: str, url: str) -> dict | None:
    if board == "linkedin":
        return sources.linkedin_job(url)
    r = careers.page_get(url)
    for d in careers.postings_on(r.text) if r is not None and r.ok else []:
        j = careers.from_posting(d, url, f"email alert ({board})")
        if j["title"] and len(j["description"]) >= 200:
            return j | {"id": f"alert:{url}"}
    log.info("alert link without readable job data: %s", url)
    return None


def collect(cand, store, dry: bool = False) -> list[dict]:
    """New job alerts since the last run (the last 3 days on the first run)."""
    if not enabled(cand):
        return []
    try:
        box = _connect(cand)
    except (imaplib.IMAP4.error, OSError) as e:
        log.warning("job alert mailbox unreachable: %s", e)
        return []
    jobs, resolved, country = [], 0, targets.country(cand.config)
    try:
        last = int(store.get("alerts_uid", "0") or 0)
        if last:
            _, data = box.uid("search", None, f"UID {last + 1}:*")
        else:
            _, data = box.uid("search", None, f'SINCE {(datetime.now() - timedelta(days=3)):%d-%b-%Y}')
        uids = [int(u) for u in (data[0] or b"").split() if int(u) > last]
        seen: set[str] = set()
        for uid in uids:
            _, msg_data = box.uid("fetch", str(uid), "(BODY.PEEK[])")
            raw = next((part[1] for part in msg_data if isinstance(part, tuple)), b"")
            message = email.message_from_bytes(raw)
            if not SENDERS.search(parseaddr(message.get("From", ""))[1]):
                continue
            try:
                posted = parsedate_to_datetime(message.get("Date", "")).date().isoformat()
            except (TypeError, ValueError):
                posted = ""
            for url, text, block in links_in(message):
                hit = job_link(url)
                if not hit and TRACKER.search(urlparse(url).netloc + urlparse(url).path) and resolved < MAX_RESOLVE:
                    resolved += 1
                    hit = job_link(_resolve(url))
                if hit and hit[1] not in seen:
                    seen.add(hit[1])
                    board, link = hit
                    j = None if board in BLOCKS_BOTS else to_job(board, link)
                    j = j or from_block(board, link, text, block, posted, country)
                    if j:
                        jobs.append(j | {"tier_hint": ""})
        if uids and not dry:
            store.put("alerts_uid", str(max(uids)))
    except (imaplib.IMAP4.error, OSError) as e:
        log.warning("job alerts: %s", e)
    finally:
        try:
            box.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
    log.info("job alerts: %d postings from the mailbox", len(jobs))
    return jobs

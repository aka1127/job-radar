"""One cycle: boards + career pages -> filters -> AI score -> pack -> ATS + screener checks -> deliver."""
import html
import json
import logging
import random
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import alerts, archive, ats, careers, harvest, logos, opendata, sitemaps, sources, targets
from .candidate import ROOT, file_part
from .llm import Claude, UsageLimit
from .notify import Telegram, alert, brief_text, deliver, first_line, outreach_text, people_search_url
from .docx_cv import cv_docx
from .render import Renderer, plain_text, unbold
from .store import DELIVERED, Store, dedupe_key, now, short_id
from .text import clean_title, detect_lang, display_title, slug

log = logging.getLogger("hunter")
CV_KEYS = ("headline", "summary", "strengths", "skills", "experience")
TIERS = {"home_region": 1, "remote_france": 1, "other_france": 2, "paris_region": 1}  # paris_region: older scores


AI_WORDS = re.compile(r"\b(?:AI|IA|LLMs?|GenAI)\b|intelligence artificielle|artificial intelligence", re.I)


def _ids(cv: dict) -> list[str]:
    """The profile jobs this CV shows; the ATS check verifies those."""
    return [x["id"] for x in cv.get("experience", [])]


def tidy_skills(skills: list[dict]) -> list[dict]:
    """AI stays a supporting skill: a group named after it ("AI & Content", "Outils IA") loses the AI part of its
    label, or joins the last other group when nothing else is left of the label."""
    out = []
    for g in skills:
        label = AI_WORDS.sub("", g["label"]).strip(" &/,-")
        if not AI_WORDS.search(g["label"]):
            out.append(g)
        elif label and label.lower() not in ("tools", "outils"):
            out.append(g | {"label": label})
        elif out:
            out[-1] = out[-1] | {"items": out[-1]["items"] + [i for i in g["items"] if i not in out[-1]["items"]][:1]}
    return out


def title_filter(cfg: dict):
    must = re.compile(cfg["title_must_match"], re.I)
    must_not = re.compile(cfg["title_must_not_match"], re.I)
    return lambda title: bool(title) and bool(must.search(title)) and not must_not.search(title)


def window_hours(store: Store, cfg: dict) -> int:
    last = store.get("last_run")
    if not last:
        return cfg["scraping"]["first_run_hours"]
    since = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
    return max(cfg["scraping"]["min_window_hours"], int(since) + 1)


def board_due(store: Store, cfg: dict, board: str) -> bool:
    """LinkedIn blocks frequent visitors: it runs every few hours (board_every_hours) and rests 2 hours after a
    block. Its next run looks back to its last good one, so pacing loses no job."""
    def hours_since(key: str) -> float:
        at = store.get(key)
        return (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds() / 3600 if at else 1e9
    every = cfg["scraping"].get("board_every_hours", {}).get(board, 0)
    return hours_since(f"last_ok_{board}") >= every - 0.25 and hours_since(f"blocked_{board}") >= 2


def board_windows(store: Store, cfg: dict, hours: int) -> dict[str, int]:
    """Each board looks back to its last run that was not rate-limited, so the hours lost to a block are
    searched once it lifts (at most first_run_hours)."""
    out = {}
    for b in sources.BOARDS:
        last = store.get(f"last_ok_{b}")
        since = ((datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600 if last
                 else cfg["scraping"]["first_run_hours"])  # a board never searched yet looks back the full first window
        out[b] = min(cfg["scraping"]["first_run_hours"], max(hours, int(since) + 1))
    return out


def prefilter(jobs: list[dict], title_ok, store: Store) -> list[dict]:
    out, keys = [], set()
    for j in jobs:
        k = dedupe_key(j)
        if k in keys or not title_ok(j["title"]) or not store.is_new(j):
            continue
        keys.add(k)
        out.append(j)
    return out


def with_descriptions(cands: list[dict], store: Store, cfg: dict, dry: bool) -> list[dict]:
    """Phase 2: open job pages only for postings that passed the filters, within a budget per run."""
    details, budget, ready = sources.Details(), cfg["scraping"]["max_details_per_run"], []
    for j in cands:
        if len(j["description"]) < 200 and budget > 0 and j["site"] in ("linkedin", "hellowork"):
            j["description"] = details.fetch(j) or j["description"]
            budget -= 1
            time.sleep(random.uniform(*cfg["scraping"]["pause_between_details_s"]))
        if len(j["description"]) >= 200 or j.get("summary_only"):  # alert summaries are all there is
            ready.append(j)
        elif not dry:
            j["tries"] = int(j.get("tries") or 0) + 1
            store.save(j, "pending" if j["tries"] < 4 and j["site"] in ("linkedin", "hellowork") else "no_description")
    return ready


STRICT_PORTALS = re.compile(r"myworkdayjobs|myworkdaysite|workday\.com|taleo\.net|successfactors|sapsf|jobs\.sap\.com|"
                            r"icims\.com|oraclecloud\.com|brassring|kenexa|csod\.com|avature\.net", re.I)
PORTAL_NAMES = [("workday", "Workday"), ("taleo", "Taleo"), ("successfactors|sapsf|jobs.sap", "SuccessFactors"),
                ("icims", "iCIMS"), ("oraclecloud", "Oracle"), ("brassring|kenexa", "BrassRing"),
                ("csod", "Cornerstone"), ("avature", "Avature")]


def portal_name(url: str) -> str:
    return next((name for pattern, name in PORTAL_NAMES if re.search(pattern, url or "", re.I)), "")


def file_tag(company: str) -> str:
    return file_part(company, 25) or "Entreprise"


def target_brand(cand, job: dict, brief: dict | None) -> dict | None:
    """The target company's brand color, taken from its real logo, to tint the designed CV and letter.
    No logo is shown (a lone company logo can read as a past employer); the color shows the research."""
    company = job["company"].strip()
    if not cand.config.get("brand_colors", True) or not company or re.search(r"confidenti|anonym|undisclosed", company, re.I):
        return None
    domain = re.sub(r"^https?://|^www\.|/.*$", "", ((brief or {}).get("website") or "").strip().lower())
    folder, key = ROOT / "data" / "logos", slug(company, 40)
    if domain:
        logo = logos.ensure(folder, key, company, domain, monogram_ok=False)
    else:  # no research this time: reuse a logo fetched for an earlier posting
        logo = folder / f"{key}.png" if (folder / f"{key}.png").exists() else None
    color = logos.brand_color(logo) if logo else None
    return {"company": company, "url": job["apply_url"] or job["url"], "color": color or "",
            "logo": str(logo) if logo else ""}  # the logo only heads the Telegram message, never the CV


def build(cand, claude: Claude, renderer: Renderer, job: dict, fit: dict, lang: str, tier: int | None) -> dict:
    company = slug(job["company"], 20)
    folder = cand.out / datetime.now().strftime("%Y-%m-%d") / f"{company}_{slug(clean_title(job['title']), 30)}"
    # Names a recruiter sees: plain and personal, never a hint of how the file was made.
    # Hyphens, no spaces: portals store the name with the application ("Alex-Moreau-CV-Alan.pdf").
    tag = file_tag(job["company"])
    final_pdf = folder / f"{cand.file_stem}-CV-{tag}.pdf"
    alt_pdf = folder / "autre_version" / f"{cand.file_stem}-CV-{tag}.pdf"
    letter_pdf = folder / f"{cand.file_stem}-{'Lettre' if lang == 'fr' else 'Cover-Letter'}-{tag}.pdf"
    pdf = folder / ".work" / "cv.pdf"  # draft used by the checks and revisions

    frame = targets.framing(fit, cand.config)
    pack = claude.pack(job, fit, lang, frame)
    pack["skills"] = tidy_skills(pack["skills"])
    for key in ("cover_letter", "linkedin_note", "hiring_manager_message", "follow_up"):
        pack[key] = unbold(pack[key])  # bold markers are for CV lines only
    pack["interview_angles"] = [unbold(a) for a in pack["interview_angles"]]
    brief = None
    if cand.config.get("company_brief", True):
        try:
            brief = claude.brief(job, lang)
        except UsageLimit:
            raise
        except Exception as e:
            log.warning("company brief failed for %s: %s", job["company"], e)
    target = target_brand(cand, job, brief)
    cv = {k: pack[k] for k in CV_KEYS} | {"lang": lang, "target": target, "framing": frame}
    pages, scale = renderer.cv_pdf(cv, cand, pdf)
    check = ats.check(pdf, fit["keywords"], job["title"], lang, cand, job["company"], max_pages=2, ids=_ids(cv))
    screen = claude.screen(job, check["text"])

    # Up to two honest revisions: one when the ATS or the screener is not convinced, more if over two pages.
    for attempt in range(2):
        if not (pages > 2 or (attempt == 0 and (check["coverage"] < 80 or screen["score"] < 75))):
            break
        cv2 = claude.revise(job, cv, lang, check["missing"], screen, shorter=pages > 2, framing=frame,
                            score=fit["score"]) | {
            "lang": lang, "target": target, "framing": frame}
        cv2["skills"] = tidy_skills(cv2["skills"])
        tmp = folder / ".work" / "candidate.pdf"
        pages2, scale2 = renderer.cv_pdf(cv2, cand, tmp)
        check2 = ats.check(tmp, fit["keywords"], job["title"], lang, cand, job["company"], max_pages=2,
                           ids=_ids(cv2))
        screen2 = claude.screen(job, check2["text"])
        if pages2 <= 2 and (pages > 2 or check2["score"] + screen2["score"] > check["score"] + screen["score"]):
            tmp.replace(pdf)
            cv, check, screen, pages, scale = cv2, check2, screen2, pages2, scale2
            pack.update({k: cv2[k] for k in CV_KEYS})
        else:
            tmp.unlink(missing_ok=True)

    # One CV goes out: the designed one, or the plain one when the job is applied through a strict corporate
    # portal (Workday, Taleo...). The other version is kept in autre_version/ under the same name.
    strict = bool(STRICT_PORTALS.search(job["apply_url"] or job["url"] or ""))
    pages, scale = renderer.cv_pdf(cv, cand, final_pdf, plain=strict)
    renderer.cv_pdf(cv, cand, alt_pdf, plain=not strict)
    docx = None
    if strict:  # the scores shown must be those of the file that goes out
        check = ats.check(final_pdf, fit["keywords"], job["title"], lang, cand, job["company"], max_pages=2,
                          ids=_ids(cv))
        # These portals read Word best, so for these jobs only the plain CV goes out as .docx.
        docx = cv_docx(cv, cand, folder / f"{cand.file_stem}-CV-{tag}.docx")
    shutil.rmtree(folder / ".work", ignore_errors=True)
    pdf = final_pdf
    renderer.letter_pdf(pack["cover_letter"], job, cv["headline"], cand, lang, letter_pdf,
                        (target or {}).get("color"), frame)
    flags = ats.truth_flags("\n".join([plain_text(cv, cand), pack["cover_letter"], pack["linkedin_note"],
                                       pack["hiring_manager_message"]]), cand, job["description"])
    flags += ats.unbacked_tools(plain_text(cv, cand), cand)  # on the CV every tool is a claim
    try:  # the picture that opens the job in Telegram; the card goes as plain text without it
        banner = renderer.banner(job, fit, target, folder / "banner.png", cand.config)
    except Exception as e:
        log.warning("banner failed for %s: %s", job["company"], e)
        banner = None

    (folder / "posting.md").write_text(f"# {job['title']} | {job['company']}\n\n{job['url']}\n\n{job['description']}",
                                       encoding="utf-8")
    (folder / "pack.md").write_text(
        f"# {job['title']} | {job['company']}\n\nApply: {job['apply_url'] or job['url']}\n\n"
        f"Find the hiring manager: {people_search_url(job['company'], (pack['hiring_manager_titles'] or [''])[0])}\n\n"
        f"Fit {fit['score']}/100 | ATS {check['score']}/100 (keywords {check['coverage']}%, missing: "
        f"{', '.join(check['missing']) or 'none'}) | AI screener {screen['score']}/100 ({screen['verdict']})\n"
        f"ATS notes: {'; '.join(check['issues']) or 'none'}\nScreener concerns: {'; '.join(screen['concerns']) or 'none'}\n"
        f"Truth flags: {'; '.join(flags) or 'none'}\n\n## Cover letter\n\n{pack['cover_letter']}\n\n"
        f"## Outreach\n\n{outreach_text(pack)}\n\n## Company brief\n\n{brief_text(brief)}\n", encoding="utf-8")
    (folder / "cv.json").write_text(json.dumps(cv, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(pack=pack, pdf=pdf, alt_pdf=alt_pdf, plain=strict, letter_pdf=letter_pdf, folder=folder, lang=lang, tier=tier, pages=pages,
                scale=scale, ats={k: v for k, v in check.items() if k != "text"}, screen=screen, flags=flags,
                brief=brief, banner=banner, docx=docx, portal=portal_name(job["apply_url"] or job["url"]) if strict else "")


def ship(cand, store: Store, claude: Claude, renderer: Renderer, job: dict, fit: dict, lang: str, tier):
    res = build(cand, claude, renderer, job, fit, lang, tier)
    cb = short_id(job["id"])
    delivered = deliver(cand, job, fit, res, cb)
    store.save(job, "sent" if delivered else "undelivered", fit["score"], tier, {
        "fit": fit, "lang": lang, "ats": res["ats"], "screen": res["screen"], "flags": res["flags"],
        "folder": str(res["folder"]), "pdf": str(res["pdf"]), "letter": str(res["letter_pdf"]),
        "follow_up": res["pack"]["follow_up"], "linkedin_note": res["pack"]["linkedin_note"],
        "pack": res["pack"], "brief": res["brief"], "banner": str(res["banner"] or ""),
        "docx": str(res["docx"] or ""), "portal": res["portal"],
        "sent_on": datetime.now(timezone.utc).date().isoformat()})
    log.info("%s: %s | %s (fit %s, ATS %s, screener %s, %s, tier %s)", "sent" if delivered else "NOT DELIVERED",
             job["title"], job["company"], fit["score"], res["ats"]["score"], res["screen"]["score"], lang, tier)
    return res


def redeliver(cand, store: Store):
    """Packs Telegram did not take last time (network or Telegram outage) go out before anything new."""
    for row in store.db.execute("select * from jobs where status='undelivered'").fetchall():
        d = json.loads(row["data"] or "{}")
        try:
            res = {"pdf": Path(d["pdf"]), "letter_pdf": Path(d["letter"]), "pack": d["pack"], "brief": d.get("brief"),
                   "ats": d["ats"], "screen": d["screen"], "flags": d["flags"], "lang": d["lang"],
                   "tier": row["tier"], "folder": d["folder"], "banner": d.get("banner") or None,
                   "docx": d.get("docx") or None, "portal": d.get("portal", "")}
            if deliver(cand, json.loads(row["job"]), d["fit"], res, row["cb"]):
                store.set_status(row["id"], "sent")
                log.info("delivered late: %s | %s", row["title"], row["company"])
        except (KeyError, OSError) as e:  # files gone or an old record: rebuild it from scratch instead
            log.warning("cannot redeliver %s: %s", row["title"], e)
            store.set_status(row["id"], "queued")


def grow_watchlist(cand, store: Store, raw: list[dict], cands: list[dict]):
    learned = careers.learn(store, raw)
    probed = 0
    for j in cands[: cand.config["career_pages"]["max_new_companies_per_run"]]:
        probed += bool(careers.probe(store, j["company"]))
    log.info("career pages: %d boards learned from apply links, %d found by probing", learned, probed)


def discover(cand, store: Store, claude: Claude):
    """Once a day, Claude searches the web for company career pages beyond the job boards."""
    last = store.get("last_discover")
    every = timedelta(hours=cand.config["career_pages"]["discover_every_hours"])
    if last and datetime.now(timezone.utc) - datetime.fromisoformat(last) < every:
        return
    already = [r["name"] for r in store.companies()]
    added = 0
    for r in claude.discover(cand.config["searches"][:12], already):
        added += bool(careers.add_url(store, r["url"], r["company"], "web discovery"))
    store.put("last_discover", now())
    log.info("career pages: %d added by web discovery (%d watched)", added, len(store.companies()))


def remind(cand, store: Store):
    """Nudge to send the follow-up a few days after applying."""
    tg = Telegram(cand)
    days = cand.config.get("followup_after_days", 7)
    for row in store.followups_due(days):
        follow_up = json.loads(row["data"] or "{}").get("follow_up", "")
        if tg.enabled:
            sent = tg.send(f"⏰ <b>Follow-up time</b>: {html.escape(display_title(row['title']))} · "
                           f"{html.escape(row['company'])}\nYou applied {days} days ago. Send this to the person "
                           f"you contacted (or reply to your application email):\n<pre>{html.escape(follow_up)}</pre>",
                           {"inline_keyboard": [[{"text": "✅ Follow-up sent", "callback_data": f"f:{row['cb']}"}]]})
            if not sent.get("ok"):
                continue  # Telegram did not take it: try again next run
        store.set_status(row["id"], "followed_up")


SOURCES = {"linkedin": "LinkedIn", "indeed": "Indeed", "hellowork": "HelloWork", "france_travail": "France Travail",
           "sent by link": "your links"}


def weekly_summary(cand, store: Store, when: datetime | None = None):
    """Monday morning: what went out last week, what came of it, and the best match still waiting."""
    when = when or datetime.now()
    week = when.strftime("%G-W%V")
    tg = Telegram(cand)
    if not tg.enabled or when.weekday() != 0 or when.hour < 8 or store.get("weekly_sent") == week:
        return
    since = (when - timedelta(days=7)).date().isoformat()
    rows = store.db.execute(f"select * from jobs where status in {DELIVERED}").fetchall()
    sent = [r for r in rows if json.loads(r["data"] or "{}").get("sent_on", "") >= since]
    in_week = lambda col: sum(bool(r[col]) and r[col][:10] >= since for r in rows)  # noqa: E731
    by_source: dict[str, int] = {}
    for r in sent:
        name = SOURCES.get(r["site"], "company sites" if r["site"].startswith("career page") else r["site"])
        by_source[name] = by_source.get(name, 0) + 1
    waiting = [r for r in rows if r["status"] == "sent"]
    best = max(waiting, key=lambda r: r["score"] or 0) if waiting else None
    applied = sum(bool(r["applied_at"]) for r in rows)
    interviews = sum(bool(r["interview_at"]) for r in rows)
    lines = [f"📊 <b>Your week</b> ({(when - timedelta(days=7)):%d %b} to {when:%d %b})",
             f"• Jobs sent: {len(sent)}" + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(
                 by_source.items(), key=lambda kv: -kv[1])) + ")" if by_source else ""),
             f"• Applied: {in_week('applied_at')} · Interviews: {in_week('interview_at')} · "
             f"Offers: {sum(r['status'] == 'offer' and (r['outcome_at'] or '')[:10] >= since for r in rows)} · "
             f"Rejected: {sum(r['status'] == 'rejected' and (r['outcome_at'] or '')[:10] >= since for r in rows)}"]
    if best:
        lines.append(f"• Waiting for your decision: {len(waiting)}. Best: <b>{html.escape(display_title(best['title']))}"
                     f" · {html.escape(best['company'])}</b> ({best['score']}/100)")
    if applied:
        lines.append(f"• Since the start: {interviews} interview{'s' * (interviews != 1)} from {applied} "
                     f"application{'s' * (applied != 1)} ({round(100 * interviews / applied)}%)")
    if tg.send("\n".join(lines)).get("ok"):
        store.put("weekly_sent", week)


def watch_usage(cand, store: Store):
    """One Telegram heads-up per day when Claude calls pass the configured threshold."""
    from .llm import usage_by_day

    today = (usage_by_day(1) or [{"day": "", "calls": 0}])[0]
    limit = cand.config["claude"].get("daily_call_warning", 400)
    if today["calls"] >= limit and store.get("usage_warned") != today["day"]:
        log.warning("Claude usage: %d calls today (warning at %d)", today["calls"], limit)
        alert(cand, f"Claude usage: {today['calls']} calls today (heads-up threshold {limit}). "
                    "Nothing is blocked; see python -m hunter usage.")  # admin chat, never the candidate's
        store.put("usage_warned", today["day"])


def score_order(job: dict, home: set[str] = frozenset()) -> tuple:
    """Who is scored first when there are too many: the core targets of the triage, then the candidate's home
    region (its departments) and remote jobs, then the freshest."""
    loc = job.get("location") or ""
    near = archive.department(loc) in home or bool(re.search(r"t[ée]l[ée]travail|remote", loc, re.I))
    return (job.get("triage") == "core", near, job.get("posted") or "")


def triage(claude: Claude, jobs: list[dict], store: Store, batch: int = 80) -> list[dict]:
    """Before the full scoring (one Claude call per posting), one quick call per batch sorts the new postings from
    their titles: core, possible or skip. Skipped ones are saved as such and cost nothing more. Postings sorted on
    an earlier run keep their verdict; when a call fails, its batch goes on to the full scoring."""
    todo = [j for j in jobs if not j.get("triage")]
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        try:
            verdicts = claude.triage(part)
        except UsageLimit:
            raise
        except Exception as e:
            log.warning("triage failed, the full scoring decides: %s", first_line(e))
            continue
        for j, verdict in zip(part, verdicts):
            j["triage"] = verdict
    kept = []
    for j in jobs:
        if j.get("triage") == "skip":
            store.save(j, "skipped", data={"triage": "skip"})
        else:
            kept.append(j)
    if todo:
        log.info("triage of %d postings: %d core, %d possible, %d skipped", len(todo),
                 sum(j.get("triage") == "core" for j in todo), sum(j.get("triage") == "possible" for j in todo),
                 sum(j.get("triage") == "skip" for j in todo))
    return kept


def scores_today() -> int:
    from .llm import usage_by_day

    today = (usage_by_day(1) or [{}])[0]
    return (today.get("steps") or {}).get("score", 0) if today.get("day") == datetime.now().date().isoformat() else 0


def cap_scoring(ready: list[dict], store: Store, limit: int, home: set[str] = frozenset()) -> list[dict]:
    """At most `limit` Claude scores this run, the candidate's region and the freshest postings first; the rest wait
    as pending for the next runs, so a big catch-up never burns the day's Claude usage in one go."""
    if len(ready) <= limit:
        return ready
    ready = sorted(ready, key=lambda j: score_order(j, home), reverse=True)
    for j in ready[limit:]:
        store.save(j, "pending")
    log.info("scoring %d postings now (region and freshest first), %d wait for the next runs", limit,
             len(ready) - limit)
    return ready[:limit]


def paused_hours(store: Store, limit: float = 3.0) -> int:
    """Hours since the last finished cycle when that is over `limit` (a cycle normally ends about every hour)."""
    last = store.get("last_run")
    if not last:
        return 0
    gap = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
    return round(gap) if gap > limit else 0


def sending_hours(cfg: dict, now: datetime | None = None) -> bool:
    """Packs, follow-ups and summaries reach the candidate only between send_hours (default 8:00 to midnight)."""
    start, end = cfg.get("send_hours", [8, 24])
    return start <= (now or datetime.now()).hour < end


def run(cand, dry: bool = False, hours: int | None = None, limit: int | None = None,
        boards: bool = True, career_pages: bool = True):
    cfg, store = cand.config, Store(cand)
    title_ok = title_filter(cfg)
    started = now()
    paused = paused_hours(store)
    if paused and not dry:  # the loop runs about hourly: a longer gap means the PC slept or the hunter stopped
        alert(cand, f"The hunter was paused for about {paused} hours (PC asleep, lid closed or the program stopped). "
                    "It is catching up now: no job from that time is lost.")
    awake = sending_hours(cfg)
    if not dry and awake:
        redeliver(cand, store)
    windows = {b: hours for b in sources.BOARDS} if hours else None  # an explicit --hours is used as given
    hours = hours or window_hours(store, cfg)
    windows = windows or {b: h for b, h in board_windows(store, cfg, hours).items() if board_due(store, cfg, b)}
    log.info("run for %s, looking back %dh%s%s", cand.name, hours,
             "".join(f", {b} {h}h (catching up)" for b, h in windows.items() if h > hours),
             "".join(f", {b} rests this run" for b in sources.BOARDS if b not in windows))
    arch = None if dry else archive.Archive()  # every posting seen, all jobs, kept for the national database
    raw = sources.collect(cand, windows) if boards else []
    if boards and not dry:
        for b in windows:
            if b in sources.WATCH.blocked:
                store.put(f"blocked_{b}", started)
    if boards and cfg["sources"].get("email_alerts", True):
        raw += alerts.collect(cand, store, dry)  # Welcome to the Jungle, APEC, LinkedIn alerts in a mailbox
    if arch and raw:
        log.info("archive: %d new postings from the boards and alerts", arch.save(raw))
    cands = prefilter(raw, title_ok, store)
    if career_pages and cfg["sources"].get("career_pages"):
        if not dry:
            grow_watchlist(cand, store, raw, cands)
        cands += prefilter(careers.poll(store, cfg, title_ok, keep=arch.save if arch else None), title_ok, store)
    if arch:  # what the background crawlers and the France Travail harvest archived since the last run
        since = store.get("last_run") or (datetime.now(timezone.utc) - timedelta(
            hours=cfg["scraping"]["first_run_hours"])).isoformat(timespec="seconds")
        harvested = tuple(s["name"] for s in sitemaps.SITES) + ("France Travail", opendata.SOURCE)
        oldest = (datetime.now(timezone.utc) - timedelta(days=cfg["career_pages"]["max_age_days"])).date().isoformat()
        fresh = [j for j in arch.recent(since, harvested)  # still open, recent, and open to someone outside the
                 if opendata.open_for(j) and (j["posted"] or "9999") >= oldest]  # civil service
        cands += prefilter(fresh, title_ok, store)
    if not dry:
        cands += store.pending(cfg.get("pending_days", 7))
    # Same job on a board and on the company site: keep the richer copy (usually the career page).
    best: dict[str, dict] = {}
    for j in cands:
        k = dedupe_key(j)
        if k not in best or len(j["description"]) > len(best[k]["description"]):
            best[k] = j
    claude = None if dry else Claude(cand)
    found = triage(claude, list(best.values()), store, cfg["claude"].get("triage_batch", 80)) if claude \
        else list(best.values())
    ready = with_descriptions(found, store, cfg, dry)
    if not dry:
        left_today = max(0, cfg.get("max_scores_per_day", 600) - scores_today())
        ready = cap_scoring(ready, store, min(cfg.get("max_scores_per_run", 250), left_today),
                            targets.home_departments(cfg))
    log.info("%d new postings pass the filters, %d scored this run", len(cands), len(ready))
    if dry:
        for j in ready:
            print(f"- {j['title']} | {j['company']} | {j['location']} | {j['site']}")
        return

    queue = []

    def score_one(j: dict):
        try:
            return j, claude.score(j), None
        except Exception as e:
            return j, None, e

    usage_hit = None
    with ThreadPoolExecutor(cfg["claude"].get("parallel", 3)) as pool:
        scored = list(pool.map(score_one, ready))
    for j, fit, err in scored:
        if err:
            usage_hit = err if isinstance(err, UsageLimit) else usage_hit
            log.warning("scoring failed for %s: %s", j["title"], err)
            if not isinstance(err, UsageLimit):
                j["score_tries"] = int(j.get("score_tries") or 0) + 1  # a posting that always fails stops at 3
            store.save(j, "pending" if int(j.get("score_tries") or 0) < 3 else "failed")
            continue
        lang = detect_lang(j["description"]) or fit["language"]
        tier = TIERS.get(fit["location_type"])
        bar = targets.bar_for(fit, cfg)
        keep = (tier and fit["score"] >= bar[tier] and not fit["dealbreakers"]
                and fit["contract"] in cfg.get("contracts", ["CDI", "CDD", "unknown"]))
        store.save(j, "queued" if keep else "skipped", fit["score"], tier, {"fit": fit, "lang": lang})
    if boards:  # only now that every posting found is saved: a run cut short searches the same hours again
        for b in windows:
            if b not in sources.WATCH.blocked:
                store.put(f"last_ok_{b}", started)
    if usage_hit:
        raise usage_hit

    today = datetime.now(timezone.utc).date().isoformat()
    sent_today = store.db.execute("select count(*) from jobs where status!='queued' and json_extract(data, '$.sent_on')=?",
                                  (today,)).fetchone()[0]
    cap = limit or max(0, min(cfg["max_packs_per_run"], cfg["max_packs_per_day"] - sent_today))
    expired = (datetime.now(timezone.utc) - timedelta(days=cfg["queue_days"])).isoformat(timespec="seconds")
    store.db.execute("update jobs set status='expired' where status='queued' and first_seen<?", (expired,))
    store.db.commit()
    for row in store.db.execute("select * from jobs where status='queued' order by tier, score desc").fetchall():
        if store.twin_sent(row["id"], row["key"]) or store.repost_sent(json.loads(row["job"])):
            store.set_status(row["id"], "duplicate")  # same job on two boards, or reposted under another name
            continue
        data = json.loads(row["data"])
        queue.append((json.loads(row["job"]), data["fit"], data["lang"], row["tier"]))
    queue.sort(key=lambda q: not targets.priority_first(q[1], q[3], cfg))  # stable: tier and score order stay
    if queue[:cap] and awake:  # outside sending hours good matches wait in the queue
        with Renderer() as renderer:
            shipped = 0
            for j, fit, lang, tier in queue:
                if shipped >= cap:
                    break
                if store.twin_sent(j["id"], dedupe_key(j)) or store.repost_sent(j):
                    store.set_status(j["id"], "duplicate")  # its twin went out earlier in this run
                    continue
                shipped += 1
                try:
                    ship(cand, store, claude, renderer, j, fit, lang, tier)
                except UsageLimit:
                    raise
                except Exception as e:
                    log.exception("pack failed for %s: %s", j["title"], e)
                    store.save(j, "failed", fit["score"], tier, {"fit": fit, "lang": lang, "error": str(e)})
                    alert(cand, f"Pack failed: {j['title']} | {j['company']}\n{type(e).__name__}: {first_line(e)}")
    if career_pages and cfg["sources"].get("career_pages"):
        try:
            discover(cand, store, claude)
        except UsageLimit:
            raise
        except Exception as e:
            log.warning("career page discovery failed: %s", e)
    if arch:
        try:  # all offers published in France since the last harvest (needs access to Offres d'emploi v2)
            harvest.harvest_due(arch)
        except UsageLimit:
            raise
        except Exception as e:
            log.warning("France Travail harvest failed: %s", first_line(e))
    if awake:
        remind(cand, store)
        weekly_summary(cand, store)
    watch_usage(cand, store)
    store.put("last_run", now())
    write_dashboard(cand, store)
    log.info("cycle done: %s", json.dumps(store.counts()))


def job_from_url(cand, claude: Claude, url: str) -> dict | None:
    """Any job link: LinkedIn page, schema.org data on the page, otherwise Claude reads the page."""
    if "linkedin.com" in url:
        j = sources.linkedin_job(url)
        if j:
            return j
    j = careers.single_job(url)
    if j and len(j["description"]) >= 200:
        j["id"] = f"link:{url}"
        return j
    r = careers.get(url)
    page_text = ""
    if r is not None and r.ok:
        for d in careers.postings_on(r.text):
            j = careers.from_posting(d, url, "sent by link")
            if j["title"] and len(j["description"]) >= 200:
                j["id"] = f"link:{url}"
                return j
        page_text = careers.page_text(r.text)
    data = claude.extract(url, page_text if len(page_text) > 1500 else "")
    if not data.get("found"):
        return None
    return sources.job(id=f"link:{url}", site="sent by link", title=data["title"], company=data["company"],
                       location=data["location"], url=url, apply_url=url, description=data["description"])


def apply_to(cand, url: str) -> str:
    """Build a pack for one job link, whatever its score (the person asked for it)."""
    store, claude = Store(cand), Claude(cand)
    job = job_from_url(cand, claude, url)
    if not job:
        return "Could not read a job posting at that link."
    fit = claude.score(job)
    lang = detect_lang(job["description"]) or fit["language"]
    with Renderer() as renderer:
        ship(cand, store, claude, renderer, job, fit, lang, TIERS.get(fit["location_type"]))
    write_dashboard(cand, store)
    return f"Pack ready: {job['title']} | {job['company']} (fit {fit['score']}/100)"


def write_dashboard(cand, store: Store):
    e = html.escape
    rows = []
    for j in store.sent():
        d = json.loads(j["data"] or "{}")
        folder = d.get("folder", "")
        rel = folder.replace(str(cand.out), "").lstrip("\\/").replace("\\", "/")
        rows.append(f"<tr><td>{e(j['first_seen'][:10])}</td><td>{e(j['status'])}</td><td><b>{j['score']}</b></td>"
                    f"<td>{d.get('ats', {}).get('score', '')}</td><td>{d.get('screen', {}).get('score', '')}</td>"
                    f"<td>{e(j['title'])}</td><td>{e(j['company'])}</td><td>{e(j['location'] or '')}</td>"
                    f"<td><a href=\"{e(j['url'])}\">posting</a> · <a href=\"{e(rel)}/pack.md\">pack</a></td></tr>")
    cand.out.mkdir(parents=True, exist_ok=True)
    counts = store.counts()
    (cand.out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Job hunt</title><style>body{font:14px system-ui;margin:24px}"
        "table{border-collapse:collapse}td,th{padding:6px 10px;border-bottom:1px solid #ddd;text-align:left}</style>"
        f"<h1>{e(cand.full_name)}: applications</h1><p>{e(json.dumps(counts))}</p><table><tr><th>Date</th>"
        "<th>Status</th><th>Fit</th><th>ATS</th><th>Screener</th><th>Role</th><th>Company</th><th>Where</th>"
        f"<th>Links</th></tr>{''.join(rows)}</table>", encoding="utf-8")

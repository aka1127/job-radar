"""Command line. Run `python -m hunter --help`."""
import argparse
import json
import logging
import queue
import random
import re
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import requests
from dotenv import load_dotenv

from .candidate import ROOT, Candidate

log = logging.getLogger("hunter")


def render_base(cand):
    from .render import Renderer

    with Renderer() as r:
        for lang in ("en", "fr"):
            content = json.loads((cand.dir / f"base_{lang}.json").read_text(encoding="utf-8"))
            out = cand.dir / "cv" / f"{cand.file_stem}-CV-{lang.upper()}.pdf"
            pages, scale = r.cv_pdf(content, cand, out)
            print(f"{out.name}: {pages} page(s), scale {scale:.2f}")


def companies(cand, action: str, url: str | None):
    from . import careers
    from .store import Store

    store = Store(cand)
    if action == "add" and url:
        print("added" if careers.add_url(store, url, source="manual") else "already watched or not a URL")
    elif action == "discover":
        from .llm import Claude
        from .pipeline import discover
        store.put("last_discover", "")
        discover(cand, store, Claude(cand))
    rows = store.companies()
    for r in rows:
        print(f"{r['ats']:16} {r['name'][:40]:40} found {r['found']:3}  {r['source']}")
    print(f"{len(rows)} career pages watched")


def doctor(cand):
    """Check everything the pipeline needs, without spending much."""
    from .llm import ClaudeCode
    from .notify import Telegram

    ok = True
    cc = ClaudeCode(cand.config["claude"])
    try:
        v = subprocess.run([cc.exe, "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
        print(f"claude CLI: {v}")
        print("claude login:", cc.run("score", "Reply with the single word: ok")[:20])
    except Exception as e:
        ok = False
        print(f"claude CLI problem: {e}. Open a terminal, run `claude`, and log in once.")
    fonts = list((ROOT / "assets" / "fonts").glob("*.woff2"))
    print(f"fonts: {len(fonts)} file(s)")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        print("PDF renderer: ok")
    except Exception as e:
        ok = False
        print(f"PDF renderer problem: {e}. Run: python -m playwright install chromium")
    tg = Telegram(cand)
    if tg.token:
        me = tg.call("getMe").get("result")
        print(f"telegram bot: {'@' + me['username'] if me else 'token rejected'}; chat: {tg.chat or 'not set, run: python -m hunter telegram'}")
    else:
        print("telegram: no TELEGRAM_BOT_TOKEN in .env")
    from datetime import datetime, timedelta

    from .notify import SENT_LOG
    since = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    lines = SENT_LOG.read_text(encoding="utf-8").splitlines() if SENT_LOG.exists() else []
    sent = [json.loads(l) for l in lines if l.strip()]
    recent = [r for r in sent if r["at"] >= since]
    errors = [r for r in recent if not r["ok"]]
    print(f"telegram last 24h: {len(recent)} messages, {len(errors)} refused"
          + (f" (last: {errors[-1]['method']}: {errors[-1]['error']})" if errors else ""))
    if errors:
        ok = False
    from . import alerts
    if alerts.enabled(cand):
        try:
            alerts._connect(cand).logout()
            print("job alert mailbox: connected")
        except Exception as e:
            ok = False
            print(f"job alert mailbox problem: {e}. Check ALERTS_IMAP_USER / ALERTS_IMAP_PASSWORD (an app password).")
    else:
        print("job alert mailbox: not set up (optional, see ALERTS_SETUP.md)")
    print("health ping:", "on" if cand.env("HEALTHCHECK_URL") else "off (optional: HEALTHCHECK_URL in .env)")
    from .store import Store
    store = Store(cand)
    print(f"career pages watched: {len(store.companies())}; jobs by status: {store.counts() or 'none yet'}")
    from .llm import usage_by_day
    today = (usage_by_day(1) or [{"calls": 0, "minutes": 0}])[0]
    print(f"Claude usage today: {today['calls']} calls, {today['minutes']:.0f} min (details: python -m hunter usage)")
    print("all good" if ok else "fix the problems above")


def usage(days: int):
    from .llm import usage_by_day

    rows = usage_by_day(days)
    if not rows:
        print("No Claude calls logged yet.")
        return
    print(f"{'day':10}  {'calls':>5}  {'min':>5}  {'input tok':>10}  {'output tok':>10}  {'API-equiv $':>11}  steps")
    for r in rows:
        steps = ", ".join(f"{k} {v}" for k, v in sorted(r["steps"].items(), key=lambda kv: -kv[1]))
        print(f"{r['day']:10}  {r['calls']:5}  {r['minutes']:5.0f}  {r['input']:10,}  {r['output']:10,}  "
              f"{r['api_equivalent_usd']:11.2f}  {steps}")
    print("API-equivalent $ is what the same calls would cost on the API; on your plan they count toward usage limits.")


def bot_only(cand):
    """Just the Telegram side (buttons, job links, /status), no scraping: handy for testing."""
    from . import bot
    from .notify import Telegram

    if not Telegram(cand).enabled:
        raise SystemExit("Telegram is not set up: run python -m hunter telegram first.")
    stop, links = threading.Event(), queue.Queue()
    threading.Thread(target=bot.worker, args=(cand, links, stop), daemon=True).start()
    log.info("telegram bot listening (Ctrl+C to stop)")
    bot.listen(cand, links, stop)


def loop(cand, every: int):
    from . import bot
    from .llm import UsageLimit
    from .notify import Telegram, alert, first_line
    from .pipeline import run

    stop, links = threading.Event(), queue.Queue()
    if Telegram(cand).enabled:
        threading.Thread(target=bot.listen, args=(cand, links, stop), daemon=True).start()
        threading.Thread(target=bot.worker, args=(cand, links, stop), daemon=True).start()
        log.info("telegram listener on")
    from . import sitemaps

    # Sites that list every offer in a sitemap (jobposting.pro...), read politely in the background into the archive.
    threading.Thread(target=sitemaps.harvest_forever, args=(stop,), daemon=True, name="sitemaps").start()
    started, broken_seen = time.time(), ""
    while True:
        if code_changed(started):  # scripts/loop.cmd starts it again at once with the new code
            broken = code_errors()
            if not broken:
                log.info("code updated: restarting to load it")
                sys.exit(RESTART)
            if broken != broken_seen:  # a half-finished edit never stops the hunter: the running version carries on
                log.warning("code updated but it does not compile, keeping the running version: %s", broken)
                alert(cand, f"New code does not compile, the hunter keeps the running version: {broken}")
                broken_seen = broken
        try:
            cand = Candidate(cand.name)  # profile and config edits apply from the next cycle, no restart needed
            ping(cand, "/start")
            run(cand)
            ping(cand)
            wait = every * 60 + random.randint(0, 300)
        except UsageLimit as e:
            m = re.search(r"\|(\d{10})", str(e))
            wait = max(600, int(m.group(1)) - int(time.time()) + 60) if m else 1800
            log.warning("Claude usage limit reached, waiting %d min: %s", wait // 60, str(e)[:120])
            alert(cand, f"Claude usage limit reached: the hunter pauses for {wait // 60} min, then carries on.")
            ping(cand)  # a planned pause, not a failure
        except Exception as e:
            log.exception("cycle failed")
            alert(cand, f"A cycle failed and will retry in 10 min: {type(e).__name__}: {first_line(e)}")
            ping(cand, "/fail")
            wait = 600
        time.sleep(wait)


RESTART = 3  # exit code that asks scripts/loop.cmd to start the hunter again


def code_changed(since: float) -> bool:
    """True when a file of the engine was edited after the loop started."""
    return any(p.stat().st_mtime > since for p in (ROOT / "hunter").glob("*.py"))


def code_errors() -> str:
    """'' when every engine file compiles, else the first syntax error (file and line)."""
    for p in sorted((ROOT / "hunter").glob("*.py")):
        try:
            compile(p.read_text(encoding="utf-8"), str(p), "exec")
        except SyntaxError as e:
            return f"{p.name} line {e.lineno}: {e.msg}"
    return ""


def ping(cand, suffix: str = ""):
    """Healthchecks.io (or any URL in HEALTHCHECK_URL): if the pings stop because the laptop slept or the
    engine died, Healthchecks warns you. Never stops the hunter."""
    url = cand.env("HEALTHCHECK_URL")
    if url:
        try:
            requests.get(url.rstrip("/") + suffix, timeout=10)
        except requests.RequestException as e:
            log.info("health ping failed: %s", e)


def main():
    load_dotenv(ROOT / ".env")
    for stream in (sys.stdout, sys.stderr):  # job titles and logs carry accents and emojis; never crash on them
        stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="hunter", description="Job hunter: boards + career pages -> tailored packs")
    who_help = "candidate folder name under candidates/ (default: the only one)"
    ap.add_argument("--who", default=argparse.SUPPRESS, help=who_help)
    ap.add_argument("--log", help="log to this file instead of the console (rotated at 5 MB, 3 old files kept)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="one full cycle")
    r.add_argument("--dry-run", action="store_true", help="scrape and filter only: no AI, nothing saved")
    r.add_argument("--hours", type=int, help="look back this many hours")
    r.add_argument("--limit", type=int, help="max application packs this run")
    r.add_argument("--no-boards", action="store_true", help="skip LinkedIn, Indeed, HelloWork, France Travail")
    r.add_argument("--no-careers", action="store_true", help="skip company career pages")
    sub.add_parser("bot", help="only the Telegram bot: buttons, job links, /status (no scraping)")
    lp = sub.add_parser("loop", help="run forever, plus the Telegram bot")
    lp.add_argument("--every", type=int, default=60, help="minutes between cycles")
    ap_ = sub.add_parser("apply", help="build a pack for one job link")
    ap_.add_argument("url")
    sub.add_parser("base", help="render the generic EN/FR CVs")
    sub.add_parser("archive", help="what the national archive of postings holds")
    sub.add_parser("opendata", help="import the State's public-sector offers file now (data.gouv.fr)")
    bd = sub.add_parser("boards", help="find company job boards with jobs in France in public ATS lists")
    bd.add_argument("--refresh", action="store_true", help="download the latest lists first")
    hv = sub.add_parser("harvest", help="France Travail national harvest into the archive (needs API access)")
    hv.add_argument("--days", type=int, default=1, help="how far back (the API keeps about 31 days)")
    lg = sub.add_parser("logos", help="fetch employer and school logos (after editing the profile)")
    lg.add_argument("--force", action="store_true", help="refetch every logo")
    tg = sub.add_parser("telegram", help="connect the candidate's Telegram chat")
    tg.add_argument("--wait", type=int, default=600, help="seconds to wait for Start in the bot chat")
    co = sub.add_parser("companies", help="career pages watched")
    co.add_argument("action", nargs="?", default="list", choices=["list", "add", "discover"])
    co.add_argument("url", nargs="?")
    sub.add_parser("doctor", help="check the setup")
    ob = sub.add_parser("onboard", help="new person: their profile and search settings written from their CV")
    ob.add_argument("name", help="folder name for the person under candidates/, e.g. alex")
    ob.add_argument("--cv", required=True, help="their CV: .pdf, .docx or .txt")
    ob.add_argument("--answers", help="YAML file with their wishes (else the questions are asked here)")
    ob.add_argument("--force", action="store_true", help="write over an existing candidate folder")
    us = sub.add_parser("usage", help="Claude calls per day (keep an eye on the subscription)")
    us.add_argument("--days", type=int, default=7)
    rs = sub.add_parser("reset", help="forget all jobs (keeps the career pages); use after testing")
    rs.add_argument("--yes", action="store_true", help="confirm")
    for p in sub.choices.values():  # --who also works after the command: hunter doctor --who alex
        p.add_argument("--who", default=argparse.SUPPRESS, help=who_help)
    a = ap.parse_args()
    handlers = [RotatingFileHandler(a.log, maxBytes=5_000_000, backupCount=3, encoding="utf-8")] if a.log else None
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    for noisy in ("httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if a.cmd == "onboard":  # the person has no folder yet
        from pathlib import Path

        from .onboard import onboard
        folder = onboard(a.name, Path(a.cv), Path(a.answers) if a.answers else None, a.force)
        print(f"Done: {folder}\nNext: read profile.yaml and config.yaml, answer QUESTIONS.md, then:\n"
              f"  python -m hunter telegram --who {a.name}\n  python -m hunter run --who {a.name} --dry-run")
        return
    cand = Candidate(getattr(a, "who", None))

    if a.cmd == "run":
        from .pipeline import run
        run(cand, a.dry_run, a.hours, a.limit, boards=not a.no_boards, career_pages=not a.no_careers)
    elif a.cmd == "bot":
        bot_only(cand)
    elif a.cmd == "loop":
        loop(cand, a.every)
    elif a.cmd == "apply":
        from .pipeline import apply_to
        print(apply_to(cand, a.url))
    elif a.cmd == "base":
        render_base(cand)
    elif a.cmd == "boards":
        from .boards import discover, fetch_lists
        from .store import Store
        folder = ROOT / "data" / "discovery"
        if a.refresh:
            print("lists fetched:", fetch_lists(folder))
        print("boards added:", discover(Store(cand), folder, folder / "france_boards.csv"))
    elif a.cmd == "opendata":
        from .archive import Archive
        from .opendata import import_due
        arch = Archive()
        arch.put("csp_checked", "2000-01-01T00:00:00+00:00")  # check data.gouv.fr now
        print(f"{import_due(arch)} new public-sector offers; archive: {arch.stats()['postings']} postings")
    elif a.cmd == "archive":
        from .archive import Archive
        print(json.dumps(Archive().stats(), indent=2, ensure_ascii=False))
    elif a.cmd == "harvest":
        from datetime import datetime, timedelta, timezone

        from .archive import Archive
        from .harvest import Harvester
        from .sources import FranceTravail
        ft = FranceTravail()
        if not ft.enabled:
            print("FRANCE_TRAVAIL_CLIENT_ID / _SECRET are not in .env")
        else:
            arch = Archive()
            new = Harvester(ft, arch).run(datetime.now(timezone.utc) - timedelta(days=a.days))
            print(f"{new} new offers; archive: {arch.stats()['postings']} postings")
    elif a.cmd == "logos":
        from .logos import refresh
        print("\n".join(refresh(cand, a.force)) or "All logos already cached (use --force to refetch).")
    elif a.cmd == "telegram":
        from .bot import setup
        setup(cand, a.wait)
    elif a.cmd == "companies":
        companies(cand, a.action, a.url)
    elif a.cmd == "doctor":
        doctor(cand)
    elif a.cmd == "usage":
        usage(a.days)
    elif a.cmd == "reset":
        from .store import Store
        if not a.yes:
            print("This forgets every job seen or sent for this candidate. Run again with --yes to confirm.")
            return
        Store(cand).reset_jobs()
        print("Jobs cleared; career pages kept.")


if __name__ == "__main__":
    main()

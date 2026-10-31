"""SQLite memory per candidate: jobs seen, packs sent, applications, and the career pages being watched."""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from .text import clean_title, fold

SCHEMA = """
create table if not exists jobs (
    id text primary key, key text, cb text, first_seen text, site text, title text, company text,
    location text, url text, score integer, tier integer, status text, job text, data text,
    applied_at text, followup_at text, interview_at text, outcome_at text);
create index if not exists jobs_key on jobs(key);
create index if not exists jobs_cb on jobs(cb);
create table if not exists companies (
    key text primary key, name text, ats text, slug text, url text, source text,
    added text, polled text, found integer default 0, active integer default 1);
create table if not exists meta (k text primary key, v text);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


GENERIC = {"france", "fr", "group", "groupe", "sa", "sas", "sasu", "sarl", "inc", "ltd", "llc", "gmbh", "holding",
           "paris", "the", "co", "company", "corp", "ag", "bv", "nv", "plc", "spa", "srl"}
KEY_VERSION = "2"
# Jobs that reached the person, whatever happened next.
DELIVERED = ("sent", "undelivered", "applied", "followed_up", "not_for_me", "interview", "rejected", "offer")


def dedupe_key(job: dict) -> str:
    """The same job posted on several boards and on the company site collapses to one key:
    'METRO France' and 'METRO', 'Thales Group' and 'Thales' are one company."""
    company = " ".join(w for w in fold(job["company"]).split() if w not in GENERIC) or fold(job["company"]).strip()
    return f'{company}|{clean_title(job["title"])}'


def same_company(a: str, b: str) -> bool:
    """One name starts the other: 'ADAGIO' and 'Adagio Aparthotel', 'Levertech' and 'Levertech (Groupe LV
    Technologies)', as boards print the same employer."""
    a, b = (fold(n).replace(" ", "") for n in (a, b))
    short, long = sorted((a, b), key=len)
    return len(short) >= 4 and long.startswith(short)


def short_id(job_id: str) -> str:
    """Compact id for Telegram buttons (callback data is limited to 64 bytes)."""
    return hashlib.sha1(job_id.encode()).hexdigest()[:12]


class Store:
    def __init__(self, cand):
        cand.db_path.parent.mkdir(exist_ok=True)
        self.db = sqlite3.connect(cand.db_path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript(SCHEMA)
        columns = {r[1] for r in self.db.execute("pragma table_info(jobs)")}
        for column in ("interview_at", "outcome_at"):  # added after the first version
            if column not in columns:
                self.db.execute(f"alter table jobs add column {column} text")
        if self.get("key_version") != KEY_VERSION:  # duplicate keys from an older version: recompute them
            for r in self.db.execute("select id, job from jobs").fetchall():
                self.db.execute("update jobs set key=? where id=?", (dedupe_key(json.loads(r["job"])), r["id"]))
            self.put("key_version", KEY_VERSION)
        if self.get("fit_version") != "2":  # scores from before the engine was generic: music_sector, paris_region
            for r in self.db.execute("select id, data from jobs where data like '%music_sector%' "
                                     "or data like '%paris_region%'").fetchall():
                data = r["data"].replace('"music_sector"', '"priority_sector"').replace('"paris_region"', '"home_region"')
                self.db.execute("update jobs set data=? where id=?", (data, r["id"]))
            self.put("fit_version", "2")

    # jobs ---------------------------------------------------------------
    def is_new(self, job: dict) -> bool:
        return self.db.execute("select 1 from jobs where id=? or key=?",
                               (job["id"], dedupe_key(job))).fetchone() is None

    def save(self, job: dict, status: str, score: int | None = None, tier: int | None = None,
             data: dict | None = None):
        self.db.execute("""insert into jobs (id, key, cb, first_seen, site, title, company, location, url, score,
                               tier, status, job, data) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           on conflict(id) do update set score=excluded.score, tier=excluded.tier,
                               status=excluded.status, job=excluded.job, data=excluded.data""",
                        (job["id"], dedupe_key(job), short_id(job["id"]), now(), job["site"], job["title"],
                         job["company"], job["location"], job["url"], score, tier, status,
                         json.dumps(job, ensure_ascii=False), json.dumps(data or {}, ensure_ascii=False)))
        self.db.commit()

    def twin_sent(self, job_id: str, key: str) -> bool:
        """The same job (other board, other company spelling) already went out."""
        return self.db.execute(f"select 1 from jobs where key=? and id!=? and status in {DELIVERED}",
                               (key, job_id)).fetchone() is not None

    def repost_sent(self, job: dict) -> bool:
        """The same offer already went out under another company name: same job title, and either a longer or
        shorter spelling of the employer ('ADAGIO', 'Adagio Aparthotel') or mostly the same description (a board or
        an agency reposts it, often hiding the employer)."""
        title = clean_title(job["title"])
        if not title:
            return False
        words = set(fold(job.get("description") or "")[:4000].split())
        for row in self.db.execute(f"select job from jobs where key like ? and id!=? and status in {DELIVERED}",
                                   (f"%|{title}", job["id"])):
            sent = json.loads(row["job"])
            if same_company(job.get("company") or "", sent.get("company") or ""):
                return True
            other = set(fold(sent.get("description") or "")[:4000].split())
            if min(len(words), len(other)) >= 40 and len(words & other) / min(len(words), len(other)) >= 0.7:
                return True
        return False

    def pending(self, max_days: float | None = None) -> list[dict]:
        """Postings waiting for a score or a description. Those waiting longer than max_days expire: by then the
        posting is old news, and a pile that only grows would slow every run."""
        if max_days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max_days)).isoformat(timespec="seconds")
            self.db.execute("update jobs set status='expired' where status='pending' and first_seen<?", (cutoff,))
            self.db.commit()
        return [json.loads(r["job"]) for r in self.db.execute("select job from jobs where status='pending'")]

    def by_cb(self, cb: str) -> sqlite3.Row | None:
        return self.db.execute("select * from jobs where cb=?", (cb,)).fetchone()

    def set_status(self, job_id: str, status: str):
        """Dates each stage once; going back a step (Undo) clears the stages after it."""
        stamp = {"sent": "applied_at=null, followup_at=null, interview_at=null, outcome_at=null",
                 "applied": "applied_at=coalesce(applied_at, :t), interview_at=null, outcome_at=null",
                 "followed_up": "followup_at=:t",
                 "interview": "interview_at=coalesce(interview_at, :t), outcome_at=null",
                 "rejected": "outcome_at=:t", "offer": "outcome_at=:t"}.get(status)
        self.db.execute(f"update jobs set status=:s{', ' + stamp if stamp else ''} where id=:id",
                        {"s": status, "t": now(), "id": job_id})
        self.db.commit()

    def followups_due(self, days: int) -> list[sqlite3.Row]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        return self.db.execute("select * from jobs where status='applied' and applied_at<=?", (cutoff,)).fetchall()

    def sent(self) -> list[sqlite3.Row]:
        return self.db.execute(f"select * from jobs where status in {DELIVERED} order by first_seen desc").fetchall()

    def counts(self) -> dict:
        return {r[0]: r[1] for r in self.db.execute("select status, count(*) from jobs group by status")}

    def reset_jobs(self):
        """Forget every job (tests, a new person on the bot) but keep the career-page watchlist."""
        self.db.execute("delete from jobs")
        self.db.execute("delete from meta where k in ('last_run', 'tg_offset')")
        self.db.commit()

    # meta ---------------------------------------------------------------
    def get(self, k: str, default: str = "") -> str:
        row = self.db.execute("select v from meta where k=?", (k,)).fetchone()
        return row[0] if row else default

    def put(self, k: str, v: str):
        self.db.execute("insert or replace into meta values (?,?)", (k, v))
        self.db.commit()

    # career pages -------------------------------------------------------
    def add_company(self, key: str, name: str, ats: str, slug: str, url: str, source: str, active: bool = True) -> bool:
        cur = self.db.execute("""insert or ignore into companies (key, name, ats, slug, url, source, added, active)
                                 values (?,?,?,?,?,?,?,?)""", (key, name, ats, slug, url, source, now(), int(active)))
        self.db.commit()
        return cur.rowcount == 1

    def set_company(self, key: str, **fields):
        """Rename or switch off a watched company: set_company(key, name='Payhawk') or (key, active=0)."""
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"update companies set {cols} where key=?", (*fields.values(), key))
        self.db.commit()

    def seen_url(self, url: str) -> bool:
        return self.db.execute("select 1 from jobs where url=? limit 1", (url,)).fetchone() is not None

    def has_company(self, key: str) -> bool:
        return self.db.execute("select 1 from companies where key=?", (key,)).fetchone() is not None

    def companies_due(self, hours: float) -> list[sqlite3.Row]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        return self.db.execute("""select * from companies where active=1 and (polled is null or polled<=?)
                                  order by polled is not null, polled""", (cutoff,)).fetchall()

    def mark_polled(self, key: str, found: int):
        self.db.execute("update companies set polled=?, found=? where key=?", (now(), found, key))
        self.db.commit()

    def companies(self) -> list[sqlite3.Row]:
        return self.db.execute("select * from companies where active=1 order by found desc, name").fetchall()

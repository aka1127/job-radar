"""Every Claude step, run through the Claude Code CLI on your own Claude account (no API key):
score fit, write the pack, simulate the AI screener, revise, research the company, read a job page,
discover career pages."""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import targets
from .candidate import ROOT

log = logging.getLogger(__name__)
SANDBOX = Path(tempfile.gettempdir()) / "job-hunter-claude"  # empty folder: no project files or CLAUDE.md
USAGE_LOG = ROOT / "data" / "usage.jsonl"
_usage_lock = threading.Lock()
SYSTEM = ("You prepare job-application material and job-market research for one candidate. Follow the task "
          "exactly, never invent facts about the candidate, and answer in the requested format only.")


class UsageLimit(RuntimeError):
    """The Claude account hit its usage limit. The loop waits instead of failing every job."""


class ClaudeCode:
    def __init__(self, cfg: dict):
        self.exe = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")
        self.models, self.effort, self.timeout = cfg["models"], cfg["effort"], cfg.get("timeout_s", 900)
        SANDBOX.mkdir(exist_ok=True)
        # Your personal CLAUDE.md rules (language, tone) must not leak into CVs written in French.
        self.env = os.environ | {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}

    def run(self, step: str, prompt: str, schema: dict | None = None, tools: tuple[str, ...] = ()):
        args = [self.exe, "-p", "--output-format", "json", "--no-session-persistence",
                "--model", self.models.get(step, "opus"), "--effort", self.effort.get(step, "medium"),
                "--strict-mcp-config", "--disable-slash-commands",
                "--settings", json.dumps({"claudeMdExcludes": ["**/CLAUDE.md"]}),
                "--system-prompt", SYSTEM, "--tools", ",".join(tools)]
        if tools:
            args += ["--allowedTools", ",".join(tools), "--max-turns", "30"]
        if schema:
            args += ["--json-schema", json.dumps(schema)]
        for attempt in range(3):
            started = time.time()
            try:
                p = subprocess.run(args, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                   timeout=self.timeout, cwd=SANDBOX, env=self.env)
                data = json.loads(p.stdout)
            except subprocess.TimeoutExpired:
                log.warning("claude %s timed out (attempt %d)", step, attempt + 1)
                continue
            except ValueError:
                said = (p.stderr or "") + (p.stdout or "")
                if re.search(r"usage limit|limit reached|hit your limit", said, re.I):
                    raise UsageLimit(said[-300:])
                log.warning("claude %s returned no JSON: %s", step, said[-300:])
                time.sleep(10)
                continue
            result = str(data.get("result") or "")
            if data.get("is_error") or data.get("subtype") != "success":
                if re.search(r"usage limit|limit reached|hit your limit|rate limit", result, re.I):
                    raise UsageLimit(result)
                log.warning("claude %s error: %s", step, result[:300] or data.get("subtype"))
                time.sleep(10)
                continue
            log.info("claude %s: %.0fs", step, time.time() - started)
            record_usage(step, data, time.time() - started)
            if not schema:
                return result.strip()
            out = data.get("structured_output")
            if out is None:
                try:
                    out = json.loads(result)
                except ValueError:
                    continue
            return out
        raise RuntimeError(f"claude {step} failed 3 times")


def record_usage(step: str, data: dict, seconds: float):
    """One line per Claude call in data/usage.jsonl, to keep an eye on the subscription."""
    u = data.get("usage") or {}
    row = {"at": datetime.now().isoformat(timespec="seconds"), "step": step, "seconds": round(seconds),
           "model": next(iter(data.get("modelUsage") or {}), ""), "turns": data.get("num_turns"),
           "input": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
           + (u.get("cache_creation_input_tokens") or 0),
           "output": u.get("output_tokens") or 0, "api_equivalent_usd": round(data.get("total_cost_usd") or 0, 4)}
    try:
        with _usage_lock:
            USAGE_LOG.parent.mkdir(exist_ok=True)
            with open(USAGE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    except OSError as e:
        log.info("usage log not written: %s", e)


def usage_by_day(days: int = 7) -> list[dict]:
    """Calls, minutes and tokens per day, newest first."""
    since = (datetime.now() - timedelta(days=days - 1)).date().isoformat()
    totals: dict[str, dict] = {}
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            day = r["at"][:10]
            if day < since:
                continue
            t = totals.setdefault(day, {"day": day, "calls": 0, "minutes": 0.0, "input": 0, "output": 0,
                                        "api_equivalent_usd": 0.0, "steps": {}})
            t["calls"] += 1
            t["minutes"] += r["seconds"] / 60
            t["input"] += r["input"]
            t["output"] += r["output"]
            t["api_equivalent_usd"] += r["api_equivalent_usd"]
            t["steps"][r["step"]] = t["steps"].get(r["step"], 0) + 1
    return sorted(totals.values(), key=lambda t: t["day"], reverse=True)


# schemas -----------------------------------------------------------------------------------------

def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}

LOCATION_TYPES = ["home_region", "remote_france", "other_france", "abroad"]
DEALBREAKERS = ["internship or apprenticeship", "a language the candidate lacks required at native level",
                "far more years than the candidate has", "a job abroad"]


def score_schema(cfg: dict) -> dict:
    """The job families and the priority flag come from the candidate's config."""
    props = {
        "score": {"type": "integer"},
        "location_type": {"type": "string", "enum": LOCATION_TYPES},
        "language": {"type": "string", "enum": ["fr", "en"]},
        "contract": {"type": "string", "enum": ["CDI", "CDD", "freelance", "interim", "internship_or_apprenticeship",
                                                "unknown"]},
        "why_fit": _STRS, "gaps": _STRS, "dealbreakers": _STRS, "keywords": _STRS,
        "family": {"type": "string", "enum": [*(cfg.get("families") or {}), "other"]},
    }
    if targets.priority(cfg):
        props["priority_sector"] = {"type": "boolean"}
    return _obj(props)


TRIAGE_SCHEMA = _obj({"items": {"type": "array", "items": _obj({
    "n": {"type": "integer"}, "verdict": {"type": "string", "enum": ["core", "possible", "skip"]}})}})
TRIAGE_POSSIBLE = ("a role in the candidate's fields with a vague or mixed title, or a more senior title in those "
                   "fields (the full review weighs the level)")
TRIAGE_SKIP = "the work itself is in a field the targets above do not cover"


def cv_props(ids: list[str]) -> dict:
    return {"headline": _STR, "summary": _STR, "strengths": _STRS,
            "skills": {"type": "array", "items": _obj({"label": _STR, "items": _STRS})},
            "experience": {"type": "array", "items": _obj({"id": {"type": "string", "enum": ids}, "bullets": _STRS,
                                                           "alt_title": {"type": "boolean"}})}}


def headline_rule(score: int | None) -> str:
    if score is not None and score < 65:
        return (f"Fit score is {score}/100. Below 65: do NOT present the candidate as already holding the posting's "
                "title; start the headline with the closest real title from the profile, then the posting's specialty "
                "after the bar (e.g. '<a title the candidate held> | <the posting's specialty>').")
    return f"Fit score is {score}/100. The headline may start with the posting's exact title."


def framing_block(cand, framing: str) -> str:
    """The family-specific angle, and what the CV adds on its own for that family (so it is not repeated)."""
    projects = [x["name"] for x in cand.profile.get("projects", []) if framing in x.get("families", [])]
    added = (f" The CV adds a 'Projects & involvement' block on its own with: {', '.join(projects)}; do not repeat "
             "those in experience bullets." if projects else "")
    return f"FRAMING: {framing}. {targets.framing_note(cand.config, framing)}{added}"


SCREEN_SCHEMA = _obj({
    "score": {"type": "integer"}, "verdict": {"type": "string", "enum": ["advance", "maybe", "reject"]},
    "matched_requirements": _STRS, "missing_requirements": _STRS, "concerns": _STRS, "fix_suggestions": _STRS,
})
BRIEF_SNAPSHOT = "3 observations you actually verified that matter for this role (site, products, communication)"
BRIEF_SCHEMA = _obj({"what_they_do": _STR, "website": _STR, "recent_news": _STRS, "marketing_snapshot": _STRS,
                     "ideas": _STRS, "questions": _STRS, "sources": _STRS})
EXTRACT_SCHEMA = _obj({"found": {"type": "boolean"}, "title": _STR, "company": _STR, "location": _STR,
                       "description": _STR})
DISCOVER_SCHEMA = _obj({"results": {"type": "array", "items": _obj({
    "company": _STR, "url": _STR, "kind": {"type": "string", "enum": ["ats_board", "careers_page", "job_posting"]}})}})


# prompts -----------------------------------------------------------------------------------------

def rules(cand) -> str:
    extra = "".join(f"\n- {r.strip()}" for r in cand.config.get("writing_rules") or [])
    return f"""You work for {cand.full_name}, who is looking for a job. Home base: {cand.config.get('home', '')}.
You write material that gets past ATS software and AI resume screeners and into interviews.

TRUTH RULES (never break these):
- The PROFILE below is the only source of facts. Never invent tools, numbers, employers, job titles,
  dates, degrees, clients, budgets, team sizes or results.
- You may reword, reorder, select, merge and translate facts, and describe the same real thing with the
  posting's vocabulary.
- One activity often has several names: use the posting's own words for every activity the candidate's
  experience covers in substance, even when the profile words it differently. Only names of specific tools or
  platforms stay limited to the profile.
- Skills: only from skills.confirmed and skills.implied. Never from skills.to_confirm.
- Numbers: only from experience[].metrics entries that have a value, or numbers already in the profile.
- Respect the positioning notes in the profile (for example how strongly to present AI skills).
- Years of experience: use the profile's own wording, never a bigger number, and never relabel them as years in
  a narrower specialty that the job titles do not show.
- Never mention tools, sectors or skills the candidate lacks, not even to say so.
- Follow the profile's writing_notes.
- No filler that sounds like a result without one ("tied to measurable business outcomes", "drove
  significant growth"). State what was done; results only when the profile has the number.{extra}

ATS AND AI-SCREENER RULES:
- Write in the language of the posting: French posting -> everything in French; English posting ->
  everything in English. The posting language is given in the task.
- The headline starts with the posting's exact job title (cleaned of "(H/F)", "F/H/X", "CDI" and of any
  company-name prefix such as "BETC Fullsix - ") when
  the candidate's experience truthfully fits it, then " | " and 2-3 of the strongest matching specialties.
  Max 95 characters.
- Reuse the posting's exact keywords and phrases wherever they are true for the candidate. Put the
  must-haves early: headline, summary, first skills group, first bullets.
- Pair each key acronym with its long form once, in the posting's language, so a recruiter's search on
  either term finds it: FR "KPI (indicateurs clés de performance)"; EN "KPI (key performance indicators)". When
  the posting uses the long form, use its exact words.
- Skills group labels: max 20 characters. Never put languages in skills groups (they have their own section).
- No first person in bullets. Each bullet starts with a strong action (EN: past-tense verb; FR: nominal
  style like "Pilotage de..."), max 28 words.
- Plain text only: no emojis, no special symbols, no markdown except the bold markers below.

7-SECOND SCAN RULES (recruiters skim titles, employers and the first words of each line):
- In every bullet and every strength, wrap 2-5 words in **double asterisks**: the posting skill, channel or
  deliverable this line proves, within its first 6 words. Bold an outcome only when its number is in
  experience[].metrics. Exactly one bold phrase per line; never in the headline, the summary or skills.
- Short lines beat long ones: one idea per bullet, concrete nouns (tools, channels, audiences), no adjectives
  doing the work of evidence.

PROFILE (YAML):
{cand.profile_raw}"""


def _job_block(job: dict) -> str:
    note = ("\n(Only the job alert's short summary is available: work from the title and this summary, and do not "
            "assume requirements it does not state.)" if job.get("summary_only") else "")
    return (f"POSTING\nTitle: {job['title']}\nCompany: {job['company']}\nLocation: {job['location']}\n"
            f"Source: {job['site']}\nPosted: {job.get('posted') or 'unknown'}{note}\n\n{job['description'][:14000]}")


def _length(ids: list[str], shorter: bool, cfg: dict | None = None) -> str:
    neutral = (cfg or {}).get("neutral_title") or {}
    neutral = f' or a neutral "{neutral["en"]}" / "{neutral["fr"]}"' if neutral.get("en") and neutral.get("fr") else ""
    return f"""Length budget: up to two A4 pages{' (the last version was TOO LONG, over two pages: cut about 15%)' if shorter else ''}.
Detail goes where it convinces for THIS posting; never pad: every bullet states a real fact of the profile.
- summary: 2-3 sentences, max 60 words, opening with a title the candidate held{neutral}, never the posting's
  title followed by years; then the strongest proofs
- strengths: 3-4 lines, max 18 words each: "**Lead phrase**: proof" in English, "**Lead phrase** : preuve"
  in French; each proof names the employer where it happened; one per top must-have, most important first
- 5-6 skills groups of 4-9 items each, most relevant group and items first
- experience: all ids, most recent first ({', '.join(ids)}). A role the FRAMING note names gets the bullets the
  note gives it. Rank the other roles by how much they prove for this posting: the 2-3 most relevant get 4-6
  bullets each, using the profile facts in detail (what was done, for whom, with which channels and tools, at what
  scope, numbers when the profile has them); the others 2-3 bullets; the oldest 1-2.
- alt_title: true only to show the profile's title_alt for that job (when the FRAMING note allows it); else false."""


class Claude:
    """The pipeline's AI steps for one candidate."""

    def __init__(self, cand):
        self.cand = cand
        self.cc = ClaudeCode(cand.config["claude"])
        self.ids = [e["id"] for e in cand.profile["experience"]]
        self.rules = rules(cand)

    def score(self, job: dict) -> dict:
        cfg = self.cand.config
        home = cfg.get("home", "")
        families = ", ".join(f"{k} ({v})" for k, v in (cfg.get("families") or {}).items())
        p, priority = targets.priority(cfg), ""
        if p:
            priority = f"\n- priority_sector: true when {p['sector'].strip()}; false otherwise."
            if p.get("note"):
                priority += f"\n- {p['note'].strip()}"
        return self.cc.run("score", f"""{self.rules}

{_job_block(job)}

TASK: Score how likely the candidate gets an interview for this posting with a well-tailored CV.
- score 0-100. 80+: strong match on role, level and must-haves. 65-79: credible. Below 50: wrong role,
  wrong level (too junior like an internship, or director level) or missing hard requirements.
  Target level: {cfg.get('level_note', 'as the profile shows')}
- location_type: home_region (on-site/hybrid in {home or 'the candidate home region'}), remote_france (fully
  remote, open to people in France), other_france (on-site/hybrid elsewhere in France), abroad (anything else).
  The candidate lives in {home}; other_france is acceptable but lower priority.
- dealbreakers: hard blockers only ({", ".join(cfg.get("dealbreakers") or DEALBREAKERS)}). Empty if none.
- keywords: 12-20 search terms a recruiter would type into the ATS for this posting: hard skills, tools,
  channels and job-title words, 1-3 words each (e.g. "Power BI", "CRM", "gestion de projet", not whole
  sentences), written as the posting writes them, whether or not the candidate has them.
- language: the language the posting is written in.
- why_fit and gaps: 2-3 items each, in English, max 6 words per item (noun phrases, e.g. "CRM automation
  in HubSpot", "no SFMC experience").
- contract: CDI, CDD, freelance (freelance, portage, mission), interim (intérim, travail temporaire),
  internship_or_apprenticeship (stage, alternance), or unknown when the posting does not say.
- family: {families + ", " if families else ""}other.{priority}""", score_schema(cfg))

    def triage(self, jobs: list[dict]) -> list[str]:
        """One quick call sorts a batch of postings from their titles before the full scoring (one call each):
        core, possible or skip, in the order given. A posting the answer leaves out counts as possible."""
        lines = "\n".join(
            f"{n}. {j['title']} | {j.get('company') or '?'} | {j.get('location') or '?'}"
            f" | {re.sub(r'\s+', ' ', j.get('description') or '')[:160]}" for n, j in enumerate(jobs, 1))
        sort = self.cand.config.get("triage") or {}
        out = self.cc.run("triage", f"""The candidate's targets:
{self.cand.config.get('level_note', '')}

Sort each posting below (number. title | employer | place | start of the text) for this candidate:
- core: one of the targets above.
- possible: might fit: {(sort.get('possible') or TRIAGE_POSSIBLE).strip()}. When unsure, choose possible.
- skip: clearly outside the targets: {(sort.get('skip') or TRIAGE_SKIP).strip()}.

{lines}

Return one verdict for every number.""", TRIAGE_SCHEMA)
        verdicts = {i["n"]: i["verdict"] for i in out.get("items", []) if isinstance(i, dict) and "n" in i}
        return [verdicts.get(n, "possible") for n in range(1, len(jobs) + 1)]

    def pack(self, job: dict, fit: dict, lang: str, framing: str = "default") -> dict:
        language = "French" if lang == "fr" else "English"
        avail = self.cand.profile["identity"].get("availability") or ""
        availability_clause = (f", and the availability ({avail})" if avail
                               else " (availability is not confirmed: do not mention it)")
        schema = _obj(cv_props(self.ids) | {
            "cover_letter": _STR, "linkedin_note": _STR, "hiring_manager_message": _STR, "follow_up": _STR,
            "hiring_manager_titles": _STRS, "interview_angles": _STRS})
        return self.cc.run("pack", f"""{self.rules}

{_job_block(job)}

FIT ANALYSIS: {json.dumps(fit, ensure_ascii=False)}
POSTING LANGUAGE: {language}. Write the CV, the letter and every message in {language}.
{framing_block(self.cand, framing)}

TASK: Build the application pack for this posting.
1. CV content (headline, summary, strengths, skills, experience bullets), tailored to this posting. Cover every
   posting keyword that is TRUE for the candidate; skip the ones that are not.
   {headline_rule(fit['score'])}
{_length(self.ids, False, self.cand.config)}
2. cover_letter, paragraphs separated by blank lines:
   - French: 200-250 words, structure vous / moi / nous. "Madame, Monsieur," then P1: one specific fact from the
     posting and why it matters to the candidate (never say what the company is or is not looking for); P2: two
     proofs, each naming the employer; P3: what the candidate would tackle first{availability_clause}; then
     "Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées." and the full name.
   - English: 180-230 words, same structure, "Dear Hiring Team," ... "Kind regards," and the full name. Never
     translate the French closing.
   - Both: AI in one clause at most; years as the profile words them; never "I am writing to apply", "c'est exactement",
     "je suis convaincu", "passionné", "dynamique", "force de proposition", "perfect fit".
3. linkedin_note: max 180 characters (LinkedIn caps invitation notes at 200). French: "Bonjour [Prénom], je viens
   de postuler au poste de <titre> chez <entreprise>. <one proof naming an employer>. Au plaisir d'échanger.
   <first name>". English: "Hi [First name], I just applied for the <title> role at <company>. <one proof>. Happy
   to connect. <first name>". <first name> is the candidate's first name.
4. hiring_manager_message: max 110 words, sent once connected or by email. French: "Bonjour [Prénom]," with
   vous (tu only if the posting itself uses tu), the role, 2 concrete proofs naming employers, a short ask for a
   call, "Bien cordialement," and the first name. English: "Hi [First name]," ... "Best regards,". Human, not salesy.
5. follow_up: max 60 words, sent one week later. French: "Bonjour [Prénom], je me permets de revenir vers vous au
   sujet de ma candidature au poste de <titre>, envoyée la semaine dernière. <one new, specific point>. Je reste
   disponible pour un échange. Bien cordialement, <full name>". English equivalent, "Best regards,".
6. hiring_manager_titles: 2-3 job titles of the person who likely manages this role, in the posting language.
7. interview_angles: 3 talking points linking real experience to this company's needs.""", schema)

    def screen(self, job: dict, cv_text: str) -> dict:
        """Independent recruiter-side screener: sees only the posting and the parsed CV, like a real one."""
        return self.cc.run("screen", f"""You are the AI resume screener used by a company's recruiting team in
France. You compare a parsed CV with a job posting and decide who advances to a recruiter call. Be strict
and concrete. Judge only what the CV text shows.

{_job_block(job)}

PARSED CV TEXT (as extracted by the ATS):
{cv_text}

TASK: score 0-100 the match, give the verdict, list matched and missing requirements, concerns, and
fix_suggestions phrased as edits to the CV (only edits that make it clearer; you do not know the
candidate, so never suggest adding experience). Write the lists in English.""", SCREEN_SCHEMA)

    def revise(self, job: dict, cv: dict, lang: str, missing: list[str], screen: dict | None, shorter: bool,
               framing: str = "default", score: int | None = None) -> dict:
        language = "French" if lang == "fr" else "English"
        return self.cc.run("revise", f"""{self.rules}

{_job_block(job)}

CURRENT CV CONTENT: {json.dumps({k: cv.get(k) for k in ('headline', 'summary', 'strengths', 'skills', 'experience')}, ensure_ascii=False)}
ATS KEYWORDS NOT FOUND IN THE CV: {", ".join(missing) or "none"}
AI SCREENER FEEDBACK: {json.dumps(screen or {}, ensure_ascii=False)}
{framing_block(self.cand, framing)}
{headline_rule(score)}

TASK: Improve the CV content for this posting, in {language}. Work in every missing keyword that names an
activity or practice the candidate's experience covers in substance, in the posting's exact words (a skills
item, a bullet or the summary). Skip only tools and platforms the PROFILE does not list. Act on the feedback
the same way. Same truth rules.
{_length(self.ids, shorter, self.cand.config)}""", _obj(cv_props(self.ids)))

    def brief(self, job: dict, lang: str) -> dict:
        language = "French" if lang == "fr" else "English"
        return self.cc.run("brief", f"""Research this company on the web: its own site first, then recent news.
Company: {job['company']}
Role the candidate applies to: {job['title']} ({job['location']})
Company or posting URL: {job.get('company_url') or job['url']}

Candidate summary: {self.cand.profile.get('positioning', '')}

Return, in {language}, short and specific:
- what_they_do: 1-2 sentences
- website: the company's own main website domain, like "alan.com" (no https, no path); empty if unsure
- recent_news: up to 3 items (funding, launches, hiring, expansion) with month/year, empty if none found
- marketing_snapshot: {(self.cand.config.get("brief_snapshot") or BRIEF_SNAPSHOT).strip()}
- ideas: 3 concrete things the candidate could bring in the first 90 days, tied to the real skills above
- questions: 2 sharp questions to ask in the interview
- sources: the URLs you used
If you cannot find the company, say so in what_they_do and leave the lists empty.""", BRIEF_SCHEMA,
                           tools=("WebSearch", "WebFetch"))

    def extract(self, url: str, page_text: str = "") -> dict:
        """Read a job posting from any URL (used when someone sends a link). With the page text already
        downloaded, Claude copies the full posting; otherwise it opens the page itself (summarised)."""
        if page_text:
            return self.cc.run("extract", f"""This is the text of the page {url}:

{page_text[:30000]}

If it is a job posting, return the job title, the hiring company, the location and the description:
copy the missions, profile, requirements and benefits word for word in the original language, without
menus, cookie banners or other page chrome. found=false if it is not a job posting.""", EXTRACT_SCHEMA)
        return self.cc.run("extract", f"""Open this job posting and extract it: {url}
Return the job title, the hiring company, the location and the full description text (missions,
profile, requirements, benefits) in the posting's original language. found=false if the page is not a
job posting or cannot be read.""", EXTRACT_SCHEMA, tools=("WebFetch",))

    def discover(self, roles: list[str], already: list[str]) -> list[dict]:
        """Find career pages of companies hiring in France for these roles, beyond the big job boards."""
        out = self.cc.run("discover", f"""Find companies currently hiring in France for roles like:
{", ".join(roles)}.

Look for postings on company career sites and ATS job boards, NOT on LinkedIn, Indeed, HelloWork,
Welcome to the Jungle or other job boards. Useful searches include:
site:jobs.lever.co, site:job-boards.greenhouse.io, site:jobs.ashbyhq.com, site:apply.workable.com,
site:jobs.smartrecruiters.com, site:teamtailor.com, site:recruitee.com, site:jobs.personio.de,
plus French queries like "recrutement {(roles or ["marketing"])[0]} CDI {targets.home_label(self.cand.config)}" on company
"carrières" pages. Prefer the {self.cand.config.get("home") or "candidate's"} area and remote France; other French cities
are fine too.

Skip these companies, they are already watched: {", ".join(already[:300]) or "none"}.

Return up to 40 results. kind: ats_board (the company's board on one of those ATS), careers_page (a
company's own careers page listing jobs), job_posting (a single posting on a company site).
A single posting closes within weeks: when you find one, return the page that lists all the company's jobs
instead (ats_board or careers_page) and use job_posting only when no such page exists.""",
                           DISCOVER_SCHEMA, tools=("WebSearch", "WebFetch"))
        return out.get("results", [])

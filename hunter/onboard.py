"""A new person in minutes: their CV and an interview in, their profile and search settings out.

`python -m hunter onboard <name> --cv cv.pdf` reads the CV (PDF, Word or text), then interviews the person: country
and home first, then the jobs they want, their conditions, languages and proudest results. Claude reads the CV with
those answers, asks follow-up questions about what the CV leaves vague (numbers, dates, tools), then writes
candidates/<name>/profile.yaml and config.yaml in the format of candidates/example/. Every fact comes from the CV
or the answers. The files are checked (structure, country, languages, regexes) before they are saved.
`--answers answers.yaml` gives the answers up front (docs/onboarding-answers.example.yaml); follow-up questions then
go to candidates/<name>/QUESTIONS.md instead."""
import re
import sys
from pathlib import Path

import yaml

from . import geo
from .candidate import CANDIDATES, ROOT, load_yaml
from .i18n import LABELS
from .targets import CONTRACTS

EXAMPLE = CANDIDATES / "example"  # the format both files follow

# (key, question, example answer, required). Asked in this order; the country comes first.
QUESTIONS = [
    ("country", "Which country do you want to work in?", "France, Germany, United Kingdom, US, Morocco...", True),
    ("home", "Which city do you live in, or want to work around?", "Lyon", True),
    ("radius_km", "How far can you travel to work, in km?", "40", False),
    ("relocation", "Would you move for the right job? Where to?", "yes, Paris or Bordeaux / no", False),
    ("remote", "Remote, hybrid or on-site?", "any / remote only / hybrid ok", False),
    ("targets", "Which jobs do you want? Titles or fields, comma separated", "data analyst, BI developer", True),
    ("level", "At what level?", "entry / mid / senior / lead / manager", False),
    ("priority_sector", "One sector you want first, if any (empty for none)", "healthcare, sport, music, energy...", False),
    ("company_types", "What kind of employers?", "startups, large groups, public sector, NGOs, agencies...", False),
    ("avoid", "Jobs, fields or companies to avoid", "call centres, field sales, gambling", False),
    ("contracts", "Which contracts?", "permanent, fixed-term, freelance, internship, apprenticeship", True),
    ("schedule", "Full-time or part-time?", "full-time", False),
    ("salary", "Lowest yearly salary you would accept (gross, with currency)", "45000 EUR", False),
    ("availability", "When can you start?", "within a month", False),
    ("work_permit", "Are you allowed to work in that country?", "citizen / work permit / need sponsorship", False),
    ("languages", "Which languages do you speak, and how well?", "French native, English C1, Spanish B2", True),
    ("cv_languages", "In which languages should your CVs be written? (codes)", "en, fr", False),
    ("proud", "Two or three results you are proud of, with numbers if you have them", "cut reporting time by 40%", False),
    ("links", "Links to show (LinkedIn, portfolio, GitHub...)", "https://linkedin.com/in/...", False),
    ("packs_per_day", "How many tailored applications can you act on per day?", "10", False),
    ("notes", "Anything else the engine should know", "driving licence, no night shifts...", False),
]
PROFILE_KEYS = ["identity", "positioning", "writing_notes", "experience", "skills", "highlights", "education",
                "certifications", "achievements_en"]
CONFIG_KEYS = ["country", "home", "home_label", "home_radius_km", "cv_languages", "level_note", "locations",
               "min_score", "contracts", "families", "default_family", "framing_notes", "searches",
               "title_must_match", "title_must_not_match"]


def cv_text(path: Path) -> str:
    """The CV as plain text: PDF and Word files are read like an ATS reads them."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from .ats import pdf_text
        text = pdf_text(path)[0]
    elif suffix == ".docx":
        from .docx_cv import docx_text
        text = docx_text(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    if len(text.strip()) < 300:
        raise SystemExit(f"Could not read enough text from {path.name} (a scanned PDF?). Save it as .docx or .txt.")
    return text


def _interactive() -> bool:
    return sys.stdin.isatty()


def ask(answers_file: Path | None) -> dict:
    """The person's wishes, from a YAML file or asked one by one (Enter skips an optional question)."""
    if answers_file:
        answers = {k: str(v) for k, v in (load_yaml(answers_file) or {}).items() if v not in (None, "")}
    elif not _interactive():
        raise SystemExit("No terminal to ask the questions: pass --answers answers.yaml "
                         "(see docs/onboarding-answers.example.yaml).")
    else:
        print("A few questions first (Enter skips the optional ones).\n")
        answers = {}
        for key, question, example, required in QUESTIONS:
            while True:
                value = input(f"{question}{'' if required else ' (optional)'}\n  e.g. {example}\n> ").strip()
                if key == "country" and value and not geo.country_code(value):
                    print("  I do not know that country; try its English name or its code (FR, DE, US).")
                    continue
                if value or not required:
                    break
            if value:
                answers[key] = value
    missing = [k for k, _, _, required in QUESTIONS if required and not answers.get(k)]
    if missing:
        raise SystemExit(f"These answers are needed: {', '.join(missing)}.")
    code = geo.country_code(answers["country"])
    if not code:
        raise SystemExit(f"Unknown country: {answers['country']}. Use its English name or ISO code (FR, DE, US).")
    answers["country_code"], answers["country_name"] = code, geo.country_name(code)
    return answers


def follow_up(questions: list[str]) -> list[tuple[str, str]]:
    """The questions Claude asked after reading the CV, answered here (Enter skips one)."""
    print(f"\n{len(questions)} questions about your CV (Enter skips one; the more numbers, the stronger the CVs).\n")
    out = []
    for q in questions:
        a = input(f"{q}\n> ").strip()
        if a:
            out.append((q, a))
    return out


def _yaml_of(text: str) -> dict:
    """Claude's answer as YAML: the content of a ```yaml block if there is one, else the whole text."""
    m = re.search(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.S)
    data = yaml.safe_load(m.group(1) if m else text)
    if not isinstance(data, dict):
        raise ValueError("the answer is not a YAML mapping")
    return data


def check_profile(p: dict) -> list[str]:
    problems = [f"missing '{k}'" for k in PROFILE_KEYS if k not in p]
    ids = [e.get("id") for e in p.get("experience") or []]
    if len(ids) != len(set(ids)) or not all(isinstance(i, str) and re.fullmatch(r"[a-z0-9_-]+", i) for i in ids):
        problems.append("experience ids must be unique lowercase slugs")
    for e in p.get("experience") or []:
        for k in ("title_en", "company", "location", "dates", "facts"):
            if not e.get(k):
                problems.append(f"experience '{e.get('id')}' has no {k}")
    for e in p.get("education") or []:
        for k in ("degree_en", "school", "location", "dates"):
            if not e.get(k):
                problems.append(f"education '{e.get('school')}' has no {k}")
    skills = p.get("skills") or {}
    if not isinstance(skills.get("confirmed"), dict) or "implied" not in skills or "to_confirm" not in skills:
        problems.append("skills needs confirmed (groups), implied and to_confirm")
    ident = p.get("identity") or {}
    for k in ("name", "email", "location", "languages"):
        if not ident.get(k):
            problems.append(f"identity has no {k}")
    for lang in ident.get("languages") or []:
        if not all(lang.get(k) for k in ("name", "level")):
            problems.append("each language needs a name and a level")
    return problems


def check_config(c: dict) -> list[str]:
    problems = [f"missing '{k}'" for k in CONFIG_KEYS if k not in c]
    if c.get("country") and not geo.country_code(str(c["country"])):
        problems.append("country must be an ISO country code like FR, DE or US")
    unknown = [l for l in c.get("cv_languages") or [] if l not in LABELS]
    if unknown:
        problems.append(f"cv_languages can only use {', '.join(LABELS)} (not {', '.join(map(str, unknown))})")
    bad = [x for x in c.get("contracts") or [] if str(x).lower() not in CONTRACTS]
    if bad:
        problems.append(f"contracts use these names: permanent, fixed_term, freelance, interim, "
                        f"internship_or_apprenticeship, unknown (not {', '.join(map(str, bad))})")
    for key in ("title_must_match", "title_must_not_match"):
        try:
            re.compile(c.get(key) or "")
        except re.error as e:
            problems.append(f"{key} is not a valid regex: {e}")
    families = c.get("families") or {}
    if c.get("default_family") and c["default_family"] not in families:
        problems.append("default_family must be one of the families")
    if (c.get("priority") or {}).get("family") and c["priority"]["family"] not in families:
        problems.append("priority.family must be one of the families")
    if not (c.get("locations") and all("query" in l and l.get("tier") in (1, 2) for l in c["locations"])):
        problems.append("locations need a query and a tier (1 or 2)")
    if not all(str(d).isalnum() for d in c.get("home_departments") or []):
        problems.append("home_departments are French department codes like '69' or '2A'")
    if not problems:
        must = re.compile(c["title_must_match"], re.I)
        missed = [s for s in c["searches"] if not must.search(s)]
        if len(missed) > len(c["searches"]) // 3:
            problems.append(f"title_must_match misses many of the searches: {', '.join(missed[:5])}")
    return problems


def _ask_claude(cc, step: str, prompt: str, check) -> dict:
    """One call, and one retry that shows Claude what was wrong."""
    last = []
    for _ in range(2):
        text = cc.run(step, prompt + (f"\n\nYOUR LAST ANSWER HAD THESE PROBLEMS, FIX THEM: {'; '.join(last)}"
                                      if last else ""))
        try:
            data = _yaml_of(text)
        except (ValueError, yaml.YAMLError) as e:
            last = [f"not valid YAML ({e})"]
            continue
        last = check(data)
        if not last:
            return data
    raise SystemExit(f"Claude's {step} answer still has problems: {'; '.join(last)}")


def _dump(data) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=110)


def profile_prompt(cv: str, answers: dict, example: str) -> str:
    langs = answers.get("cv_languages") or f"en and the main language of {answers['country_name']}"
    return f"""Write the master profile of a job seeker as YAML, from their CV and their answers. They may work in
any field (engineering, health, sales, design, logistics, teaching, finance...): describe their own field in its
own words.

FORMAT: exactly the structure of the EXAMPLE below (same keys, same nesting, same style of values). The example
person is fictional: copy its structure, never its facts. Keys with nothing true to say get an empty list or "".

LANGUAGES: their CVs will be written in {langs}. Every text field that the CV shows exists once per CV language,
with the language code as suffix (title_en, title_fr, title_de...; degree_*, detail_*, context_*, line_*,
achievements_*; highlights as {{en: ..., fr: ...}}; languages entries get the language's own label under each
code, e.g. fr: "Anglais : courant (C1)"). English is always one of them.

RULES:
- Every fact comes from the CV or the answers. Never invent employers, titles, dates, tools, numbers or results.
- experience: one entry per job, most recent first. id: a short lowercase slug of the employer. dates: "Mon YYYY -
  Mon YYYY" or "Mon YYYY - Present" with English month abbreviations. facts: everything the CV and the answers say
  about the job, one fact per line, complete and specific. metrics: only numbers the CV or the answers state, else
  {{}}. domain: "" (logos are drawn from the name).
- skills.confirmed: groups of tools and skills the CV shows in use. skills.implied: direct consequences of the CV.
  skills.to_confirm: tools a recruiter might test that the CV only mentions in passing.
- highlights: 4 short true facts (years of experience as the CV itself states them, counted conservatively from
  the dates only when the CV gives no number, written "N+ years of experience" and its translations; countries,
  languages, availability). highlights_creative: [] unless the
  CV has audience or portfolio numbers.
- writing_notes: 4-8 rules for writing this person's CVs and letters (how to present the main experiences, the
  years of experience wording, what never to claim, how to explain gaps or changes of field).
- positioning: 4-6 lines: who they are, years, field, strongest proofs, targets from the answers.
- Add a top-level key onboarding_questions: 6-12 short questions that would make the CV stronger: numbers behind
  results, tools to confirm, unclear dates or titles, gaps, what they did in projects.

Answer with the YAML only, in one ```yaml block.

ANSWERS:
{_dump(answers)}
CV TEXT:
{cv[:20000]}

EXAMPLE (structure only):
```yaml
{example}
```"""


def update_prompt(profile: dict, answered: list[tuple[str, str]], example: str) -> str:
    qa = "\n".join(f"Q: {q}\nA: {a}" for q, a in answered)
    return f"""Update this job seeker's profile with their answers to follow-up questions. Add the new facts and
numbers where they belong (facts, metrics, skills, highlights), fix what the answers correct, keep everything else
exactly as it is, same format. Never add anything the answers do not say. Answer with the whole updated profile
as YAML, in one ```yaml block, without onboarding_questions.

ANSWERS:
{qa}

PROFILE:
```yaml
{_dump(profile)}
```

FORMAT REFERENCE (fictional person, structure only):
```yaml
{example[:6000]}
```"""


def config_prompt(profile: dict, answers: dict, example: str) -> str:
    country = answers["country_name"]
    return f"""Write the job-search settings of this job seeker as YAML, from their profile and their answers.

FORMAT: exactly the structure of the EXAMPLE below (same keys). The example person is fictional and French: copy
its structure, never its content. The engine searches company career boards (Greenhouse, Lever, Workday...), job
alert emails and optional job boards in {country}, scores each posting with these settings and writes a tailored
CV for each good match.

RULES:
- country: {answers['country_code']}. home: their city and region; home_label: the city; home_radius_km: from the
  answers (40 if none). home_departments: only for France, the departments they can commute to (Paris: 75, 77,
  78, 91, 92, 93, 94, 95); leave it out elsewhere. locations: "<City>, {country}" tier 1, "{country}" tier 2, plus
  the cities they would move to as tier 2.
- cv_languages: from the answers, else ["en", "<main language of {country}>"]; only codes among {', '.join(LABELS)}.
- contracts: from the answers, using only: permanent, fixed_term, freelance, interim, internship_or_apprenticeship,
  plus unknown (postings that do not say).
- level_note: their core targets at the right level for their experience and answers (level, company types,
  remote, salary floor, permit), what is a stretch, what scores low.
- dealbreakers: hard blockers for them (e.g. a level far above theirs, a language they lack at native level, a job
  abroad, roles they want to avoid).
- families: 4-7 job families matching their targets, each with a one-line description; default_family: the
  broadest one. If the answers name a priority sector, add priority (family, label in capitals, tag, emoji,
  icon: star, min_score 10 points below min_score, sector, note naming their own proof for that sector);
  otherwise leave priority out.
- framing_notes: one per family: which of their real experiences lead and how many bullets each gets. Only
  employers and projects from the profile.
- writing_rules: 1-3 rules on their field's vocabulary (activities that have several names). neutral_title: a
  neutral way to name their profession in each CV language.
- triage: possible and skip in their field's terms. brief_snapshot: what to observe about an employer in their field.
- cv: creative_families (families where audience or portfolio tiles help, else []), portfolio_families,
  ai_supporting_skill (true unless AI or data is their field).
- max_packs_per_day: from the answers (10 if none).
- searches: 20-40 short search terms as job boards in {country} use them (the local language and English), most
  important first. title_must_match and title_must_not_match: case-insensitive Python regexes on job titles, in the
  local language and English; must_match catches every search term and their variants; must_not_match drops
  internships, apprenticeships and freelance unless wanted, and the fields and levels they do not target.

Write every list as a block list, one item per line. Answer with the YAML only, in one ```yaml block.

ANSWERS:
{_dump(answers)}
PROFILE:
{_dump(profile)[:20000]}

EXAMPLE (structure only):
```yaml
{example}
```"""


def onboard(name: str, cv_path: Path, answers_file: Path | None = None, force: bool = False,
            root: Path = CANDIDATES) -> Path:
    from .llm import ClaudeCode

    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,30}", name):
        raise SystemExit("The name is a folder name: lowercase letters, digits, - or _ (e.g. alex).")
    folder = root / name
    if folder.exists() and not force:
        raise SystemExit(f"candidates/{name} already exists (use --force to write over it).")
    text = cv_text(cv_path)
    answers = ask(answers_file)
    cc = ClaudeCode(load_yaml(ROOT / "config.yaml")["claude"])
    example_profile = (EXAMPLE / "profile.yaml").read_text(encoding="utf-8")
    print("Reading the CV with your answers (a minute or two)...")
    profile = _ask_claude(cc, "onboard", profile_prompt(text, answers, example_profile), check_profile)
    questions = [str(q) for q in profile.pop("onboarding_questions", []) or []]
    if questions and not answers_file and _interactive():
        answered = follow_up(questions)
        if answered:
            print("Adding your answers to the profile...")
            profile = _ask_claude(cc, "onboard", update_prompt(profile, answered, example_profile), check_profile)
            profile.pop("onboarding_questions", None)
            asked = {q for q, _ in answered}
            questions = [q for q in questions if q not in asked]
    print("Writing the search settings...")
    config = _ask_claude(cc, "onboard", config_prompt(profile, answers, (EXAMPLE / "config.yaml").read_text(
        encoding="utf-8")), check_config)
    config["country"] = answers["country_code"]
    folder.mkdir(parents=True, exist_ok=True)
    head = f"# Written by `python -m hunter onboard` from {cv_path.name}. Check every line: it is the only source of facts.\n"
    (folder / "profile.yaml").write_text(head + _dump(profile), encoding="utf-8")
    (folder / "config.yaml").write_text(head + _dump(config), encoding="utf-8")
    (folder / "QUESTIONS.md").write_text(
        "# Questions that make the CV stronger\n\nAnswer them in profile.yaml (numbers go in experience[].metrics).\n\n"
        + "".join(f"- {q}\n" for q in questions), encoding="utf-8")
    return folder

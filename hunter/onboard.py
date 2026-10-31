"""A new person in minutes: their CV and a few answers in, their profile and search settings out.

`python -m hunter onboard <name> --cv cv.pdf` reads the CV (PDF, Word or text), asks what the person wants (or
reads the answers from a YAML file), then Claude writes candidates/<name>/profile.yaml and config.yaml in the
same format as candidates/example/. Every fact comes from the CV; what the CV does not say becomes a question in
candidates/<name>/QUESTIONS.md. The files are checked (structure, regexes) before they are saved."""
import re
import sys
from pathlib import Path

import yaml

from .candidate import CANDIDATES, ROOT, load_yaml

EXAMPLE = CANDIDATES / "example"  # the format both files follow

QUESTIONS = [  # key, question, example answer
    ("home", "Where do you live (city or region)?", "Lyon"),
    ("targets", "Which jobs do you want? (titles or fields, comma separated)",
     "digital marketing, project manager, partnerships"),
    ("priority_sector", "One sector you want first, if any (leave empty for none)", "sport"),
    ("contracts", "Which contracts? (CDI, CDD, freelance, internship...)", "CDI, CDD"),
    ("avoid", "Jobs or fields to avoid", "call centres, field sales"),
    ("availability", "When can you start?", "within a month"),
    ("notes", "Anything else the engine should know (mobility, remote, salary...)", "open to Paris, remote ok"),
]
PROFILE_KEYS = ["identity", "positioning", "writing_notes", "experience", "skills", "highlights", "education",
                "certifications", "achievements_en", "achievements_fr"]
CONFIG_KEYS = ["home", "home_label", "home_departments", "level_note", "locations", "min_score", "contracts",
               "families", "default_family", "framing_notes", "searches", "title_must_match", "title_must_not_match"]


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


def ask(answers_file: Path | None) -> dict:
    """The person's wishes, from a YAML file (see docs/onboarding-answers.example.yaml) or asked one by one."""
    if answers_file:
        return {k: str(v) for k, v in (load_yaml(answers_file) or {}).items() if v is not None}
    if not sys.stdin.isatty():
        raise SystemExit("No terminal to ask the questions: pass --answers answers.yaml "
                         "(see docs/onboarding-answers.example.yaml).")
    out = {}
    for key, question, example in QUESTIONS:
        out[key] = input(f"{question}\n  e.g. {example}\n> ").strip()
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
        for k in ("title_en", "title_fr", "company", "location", "dates", "facts"):
            if not e.get(k):
                problems.append(f"experience '{e.get('id')}' has no {k}")
    for e in p.get("education") or []:
        for k in ("degree_en", "degree_fr", "school", "location", "dates"):
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
        if not all(lang.get(k) for k in ("name", "level", "fr")):
            problems.append("each language needs name, level and fr")
    return problems


def check_config(c: dict) -> list[str]:
    problems = [f"missing '{k}'" for k in CONFIG_KEYS if k not in c]
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


def profile_prompt(cv: str, answers: dict, example: str) -> str:
    return f"""Write the master profile of a job seeker as YAML, from their CV and their answers.

FORMAT: exactly the structure of the EXAMPLE below (same keys, same nesting, same style of values). The example
person is fictional: copy its structure, never its facts. Keys with nothing true to say get an empty list or "".

RULES:
- Every fact comes from the CV or the answers. Never invent employers, titles, dates, tools, numbers or results.
- experience: one entry per job, most recent first. id: a short lowercase slug of the employer. title_en and
  title_fr: the job title in English and French. dates: "Mon YYYY - Mon YYYY" or "Mon YYYY - Present" with English
  month abbreviations. facts: everything the CV says about the job, one fact per line, complete and specific.
  metrics: only numbers the CV states, each written in English with the French form in brackets, else {{}}.
  domain: "" (logos are drawn from the name).
- skills.confirmed: groups of tools and skills the CV shows in use. skills.implied: direct consequences of the
  CV. skills.to_confirm: tools a recruiter might test that the CV only mentions in passing.
- highlights: 4 short true facts (years of experience counted conservatively from the CV dates, written "N+
  years of experience" / "+N ans d'expérience", countries, languages, availability), in English and French.
  highlights_creative: the same kind of tiles for creative jobs, or [] when the CV has no audience numbers.
- writing_notes: 4-8 rules for writing this person's CVs and letters (how to present the main experiences, the
  years of experience wording, what never to claim).
- positioning: 4-6 lines: who they are, years, fields, strongest proofs, targets from the answers.
- languages: name, level (as the CV says, e.g. "Fluent (C1)") and fr ("Anglais : courant (C1)").
- Add a top-level key onboarding_questions: 5-10 questions to ask the person to make the CV stronger (numbers
  behind their results, tools to confirm, dates or titles that are unclear).

Answer with the YAML only, in one ```yaml block.

ANSWERS:
{yaml.safe_dump(answers, allow_unicode=True, sort_keys=False)}
CV TEXT:
{cv[:20000]}

EXAMPLE (structure only):
```yaml
{example}
```"""


def config_prompt(profile: dict, answers: dict, example: str) -> str:
    return f"""Write the job-search settings of this job seeker as YAML, from their profile and their answers.

FORMAT: exactly the structure of the EXAMPLE below (same keys). The example person is fictional: copy its
structure, never its content. The engine searches French job boards and company career pages, scores each
posting with these settings and writes a tailored CV for each good match.

RULES:
- home: their city and region; home_label: the city; home_departments: the French department codes of the area
  they can commute to (Paris: 75, 77, 78, 91, 92, 93, 94, 95); locations: "<City>, France" tier 1, "France" tier 2.
- level_note: their core targets at the right level for their experience, what is a stretch, what scores low.
- families: 4-7 job families matching their targets, each with a one-line description; default_family: the
  broadest one. If the answers name a priority sector, add priority (family, label in capitals, tag, emoji,
  icon: star, min_score 10 points below min_score, sector, note naming their own proof for that sector);
  otherwise leave priority out.
- framing_notes: one per family: which of their real experiences lead and how many bullets each gets. Only
  employers and projects from the profile.
- writing_rules: 1-3 rules on their field's vocabulary (activities that have several names).
- searches: 20-40 short search terms as French job boards use them (French and English titles), most important
  first. title_must_match and title_must_not_match: case-insensitive Python regexes on job titles; must_match
  catches every search term and their variants, must_not_match drops internships, apprenticeships, freelance
  unless wanted, and the fields and levels they do not target.
- contracts: from the answers (CDI, CDD, freelance, interim, internship_or_apprenticeship, unknown).

Answer with the YAML only, in one ```yaml block.

ANSWERS:
{yaml.safe_dump(answers, allow_unicode=True, sort_keys=False)}
PROFILE:
{yaml.safe_dump(profile, allow_unicode=True, sort_keys=False)[:20000]}

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
    print("Reading the CV and writing the profile (a minute or two)...")
    profile = _ask_claude(cc, "onboard", profile_prompt(text, answers, (EXAMPLE / "profile.yaml").read_text(
        encoding="utf-8")), check_profile)
    questions = profile.pop("onboarding_questions", []) or []
    print("Writing the search settings...")
    config = _ask_claude(cc, "onboard", config_prompt(profile, answers, (EXAMPLE / "config.yaml").read_text(
        encoding="utf-8")), check_config)
    folder.mkdir(parents=True, exist_ok=True)
    head = f"# Written by `python -m hunter onboard` from {cv_path.name}. Check every line: it is the only source of facts.\n"
    (folder / "profile.yaml").write_text(head + yaml.safe_dump(profile, allow_unicode=True, sort_keys=False, width=110),
                                         encoding="utf-8")
    (folder / "config.yaml").write_text(head + yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=110),
                                        encoding="utf-8")
    (folder / "QUESTIONS.md").write_text(
        "# Questions that make the CV stronger\n\nAnswer them in profile.yaml (numbers go in experience[].metrics).\n\n"
        + "".join(f"- {q}\n" for q in questions), encoding="utf-8")
    return folder

# Configuration

A person is a folder under `candidates/<name>/` with two files. `python -m hunter onboard` writes both from a CV
and an interview; [`candidates/example`](../candidates/example) shows every option on a fictional person.
`config.yaml` at the root holds the engine defaults; a person's `config.yaml` overrides any of them.

## profile.yaml: the facts

The only source of facts. The AI may reword, reorder, select and translate; it never adds anything.

| Key | What it holds |
|---|---|
| `identity` | name, email, phone, location, availability, links (`linkedin_url`, `portfolio_url` and their labels), photo, `languages` (name, level, and a label per CV language: `fr: "Anglais : courant (C1)"`) |
| `positioning` | 4-6 lines: who they are, years, field, strongest proofs, targets |
| `writing_notes` | rules for this person's CVs and letters (how to present a role, the years wording, what never to claim) |
| `experience` | one entry per job: `id`, `title_<lang>`, optional `title_alt_<lang>`, `company`, `context_<lang>`, `location`, `dates` ("Oct 2024 - Present"), `facts` (one per line), `metrics` (only real numbers) |
| `projects` | side projects or volunteering shown in a short block for the `families` listed |
| `skills` | `confirmed` (groups), `implied` (direct consequences of the experience), `to_confirm` (never written until confirmed) |
| `highlights` | 4 quick-fact tiles (`en`, `fr`... per CV language); `highlights_creative` for creative families |
| `education` | `degree_<lang>`, `school`, `location`, `dates`, `detail_<lang>`, optional `detail_<family>_<lang>` |
| `certifications`, `certifications_extra` | always shown; extra ones per family |
| `achievements_<lang>` | one line each |
| `other_facts`, `ai_practice`, `links`, `role_families` | context the AI may use in letters, messages and headlines |

Text fields exist once per CV language (`title_en`, `title_de`...); anything missing falls back to English.

## config.yaml: the targets

| Key | What it does |
|---|---|
| `country` | ISO code of the country to work in (`FR`, `DE`, `GB`, `US`, `MA`...), required. See [countries.md](countries.md) |
| `home`, `home_label` | home city (and region) and its short name for messages. The city must be one GeoNames knows (15,000+ people), under its local or English name; for a smaller town give the nearest such city (`doctor` warns) |
| `home_radius_km` | cities this close are the home area: tier 1 with remote jobs, scored first (default 40) |
| `home_departments` | France only, optional: departments instead of a radius |
| `cv_languages` | languages the CVs can be written in (`en, fr, es, de, it, pt, nl`); default English and the country's language |
| `locations` | board search places with their tier: `{query: "Lyon, France", tier: 1}`, `{query: "France", tier: 2}` |
| `level_note` | for the scorer: core targets, the right level, what is a stretch, what scores low |
| `min_score` | score bar per tier, exactly this shape: `{1: 55, 2: 65}` |
| `contracts` | accepted: `permanent`, `fixed_term`, `freelance`, `interim`, `internship_or_apprenticeship`, `unknown` (French `CDI`/`CDD` also understood) |
| `dealbreakers` | hard blockers the scorer looks for |
| `families` | job families with a one-line description; the scorer tags each posting with one |
| `default_family` | the family used when none fits |
| `priority` | optional sector to put first: `family`, `label`, `tag`, `emoji`, `icon` (`star`, `heart`, `health`, `bolt`, `leaf`, `briefcase`, `flag`, `pin`, `shield`, `globe`, `trophy`, `music`), `min_score` (lower bar for that family's roles, same shape as `min_score`), `sector` (what counts as that sector), `note` (what proves it) |
| `framing_notes` | per family: which experiences lead the CV and how many bullets each gets |
| `writing_rules` | extra rules for the field's vocabulary, added to every prompt |
| `neutral_title` | a neutral way to name the profession per language, for summaries |
| `triage` | `possible` and `skip`: how the quick title sort reads this field |
| `brief_snapshot` | what to observe about an employer during company research |
| `cv` | `creative_families` (audience tiles), `portfolio_families` (portfolio link in the header), `ai_supporting_skill` (AI never gets its own skills group) |
| `searches` | 20-40 search terms, most important first (the first 12 also steer web discovery) |
| `title_must_match`, `title_must_not_match` | case-insensitive regexes on job titles, the free first filter |
| `sources` | turn sources on or off for this person (board searches are off by default) |
| `max_packs_per_day` | tailored applications a day, best first |

## config.yaml at the root: the engine

| Key | What it does |
|---|---|
| `claude.models`, `claude.effort` | model and effort per step (onboard, triage, score, pack, screen, revise, brief, discover, extract) |
| `claude.triage_batch`, `claude.parallel` | postings per triage call; scoring calls at the same time |
| `sources` | job board searches (off by default), France Travail, alert emails, career pages |
| `scraping` | board search pacing and look-back windows |
| `career_pages` | how often boards are polled, the time budget per run, web discovery, maximum posting age |
| `send_hours` | packs reach the person only in these hours |
| `max_scores_per_run`, `max_scores_per_day` | caps on full AI scores |
| `max_packs_per_run`, `max_packs_per_day`, `queue_days`, `pending_days` | how many packs, how long matches wait |
| `company_brief`, `brand_colors`, `followup_after_days` | company research, brand-tinted CVs, follow-up timing |
| `crawl.user_agent` | how the crawler introduces itself (default: an honest agent naming this project) |
| `brand` | the look: `name`, `accent`, `accent_ink`, `soft` (CV and letter palette when the company gives no color), `badge` (monogram badges), `font` (family name of the files in `assets/fonts`), `priority` (`gradient`, `tag`, `tag_ink` of the Telegram header for the priority sector). Defaults in `hunter/brand.py` |
| `texts` | every sentence the person reads in Telegram, by key (`btn_applied`, `help`, `followup`, `weekly_title`...): translate or reword here, keeping the `{placeholders}`. Keys and English defaults in `hunter/brand.py` |

A person's `config.yaml` can override `brand` and `texts` too (one person in French, another in English).

## Where things live

- `HUNTER_HOME` (environment variable): the folder holding `candidates/`, `data/`, `output/` and `.env`. Unset, it
  is the checkout itself. The engine's own files (`templates/`, `assets/`, `candidates/example`) always stay with the
  code.
- `HUNTER_OUTPUT`: the packs folder, when it should differ from `<HUNTER_HOME>/output`.
- `HUNTER_CANDIDATE`: the person to use when `--who` is not given (otherwise: your only person).

## .env: secrets

Copy `.env.example`. Telegram bot token and chat ids, the alerts mailbox (an app password), optional email
delivery, optional France Travail credentials, optional health-check URL. A `_<NAME>` suffix makes a value apply
to one person only (`TELEGRAM_CHAT_ID_ALEX`). Never commit `.env`.

## The onboarding answers

Only `country`, `home`, `targets`, `contracts` and `languages` are required; the rest sharpens the settings. Your
conditions (salary floor, contracts, schedule, remote and relocation wishes, what to avoid) go to `config.yaml`
only: they never enter the profile, so they never reach a CV or a letter. `gender_titles` says which form job
titles take in languages that gender them (German, French, Spanish, Italian, Portuguese); without it the CV's own
forms are kept.

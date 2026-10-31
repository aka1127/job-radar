# Countries and languages

Job Radar works in any country. The country is the first onboarding question and lives in the person's
`config.yaml` (`country: DE`); everything location-related follows from it.

## What works everywhere

| Piece | How it adapts to the country |
|---|---|
| Company career boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Workday, Teamtailor, Recruitee, Personio) | read through their public APIs; only the jobs located in the country are kept |
| Board discovery (`python -m hunter boards --refresh`) | checks ~28,700 public ATS boards and keeps those with jobs in the country |
| Web discovery of career pages | Claude searches the web for employers hiring in the country |
| Any careers page with schema.org `JobPosting` data | `python -m hunter companies add <url>` |
| Job alert emails | LinkedIn, Indeed, Glassdoor and local boards whose emails link to their offers |
| Optional job board searches | LinkedIn anywhere; Indeed and Glassdoor in the 62 countries JobSpy supports; off by default (their terms forbid scraping) |
| Location matching | GeoNames: country names and codes, every city above 15,000 people, local names of big cities (München, Lisboa) |
| Home area | every city within `home_radius_km` of `home` (tier 1, scored first, with remote jobs) |
| Contracts | permanent, fixed_term, freelance, interim, internship_or_apprenticeship, in every country's terms |
| Scoring, screener, letters | told the country: "remote, open to people in Germany", the local letter conventions |

## France: the most complete pack

The engine was born in France, so France has extras. These start only when `country: FR`:
- France Travail's official job API (and the national harvest into the archive once access is granted).
- The State's public-sector offers: the daily open-data file and the 108 departmental feeds.
- Background crawlers of sites that publish every offer in a sitemap (jobposting.pro, Jobs that make sense).
- `home_departments`: departments instead of a radius, for a precise home area; CDI / CDD labels on the cards.

These work for whoever uses them: readers for French alert emails (APEC and Cadremploi, read from the email since
their pages refuse bots; HelloWork and Meteojob, read from their offer pages), and Welcome to the Jungle and
ProfilCulture pages added to a watchlist.

The map of ~110 French job sources, with what each allows, is in [job-boards-france.md](job-boards-france.md).

## CV languages

CVs, letters and messages can be written in **English, French, Spanish, German, Italian, Portuguese and Dutch**
(section titles, months, "present", the letter's date line, the parse checks). `cv_languages` in the config says
which ones a person uses; a posting in one of them gets a pack in its language, any other posting gets the first of
them (English when listed). The profile holds each text in each of those languages (`title_en`, `title_de`...);
anything missing falls back to English.

## Adding a language or a country pack

- **A language**: one entry in each table of `hunter/i18n.py` (section titles, months, "present", the letter
  date line, common words for detection). The tests in `tests/test_world.py` show what to check.
- **A country pack**: national job APIs, public-sector feeds or alert-email readers go in `hunter/sources.py`,
  `hunter/careers.py` or `hunter/alerts.py`, started only for that country (see how `country == "FR"` gates the
  French ones in `hunter/pipeline.py` and `hunter/main.py`). Read the source's terms and robots.txt first.

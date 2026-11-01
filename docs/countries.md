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
| Job alert emails | LinkedIn, Indeed (each country's site: de.indeed.com, www.indeed.com...), Glassdoor and local boards whose emails link to their offers; an offer whose email names no place is placed in the person's country |
| Optional job board searches | LinkedIn anywhere; Indeed and Glassdoor in the 62 countries JobSpy supports; off by default (their terms forbid scraping) |
| Location matching | GeoNames: country names and codes (also as people type them: Czech Republic, Côte d'Ivoire, Allemagne), every city above 15,000 people, local and English names (München and Munich, Lisboa and Lisbon, Köln and Cologne) |
| Home area | every spelling of every city within `home_radius_km` of `home` (tier 1, scored first, with remote jobs); "remote" is understood in the seven CV languages (remote, télétravail, Homeoffice, teletrabajo, thuiswerken...). A home town under 15,000 people is unknown to GeoNames: name the nearest bigger city (`doctor` warns) |
| Contracts | permanent, fixed_term, freelance, interim, internship_or_apprenticeship; the scorer reads each country's words (CDI, unbefristet, indefinido...); the cards print CDI / CDD in France and Permanent / Fixed-term elsewhere |
| Scoring, screener, letters | told the country: "remote, open to people in Germany", the local letter conventions. Letter and message rules are detailed for French and English; the other languages get the same structure with their usual salutations |

## France: the most complete pack

The engine was born in France, so France has extras. These start only when `country: FR`:
- France Travail's official job API (and the national harvest into the archive once access is granted).
- The State's public-sector offers: the daily open-data file and the 108 departmental feeds.
- Background crawlers of sites that publish every offer in a sitemap (jobposting.pro, Jobs that make sense).
- `home_departments`: departments instead of a radius, for a precise home area; CDI / CDD labels on the cards.
- The archive's département column and its commune lookups (geo.api.gouv.fr); elsewhere the archive keeps the
  postings without them.

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

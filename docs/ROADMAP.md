# Roadmap

Where Job Radar goes from a personal engine to something anyone can run.

## Done

- **Engine and person are separate.** Everything about a person lives in `candidates/<name>/` (`profile.yaml` for
  facts, `config.yaml` for targets): home region, job families, priority sector, CV angles, writing rules, title
  filters. The engine holds no one's data.
- **Onboarding.** `python -m hunter onboard <name> --cv cv.pdf` interviews the person (country first), asks
  follow-up questions about their CV, writes both files and checks them.
- **Triage before scoring.** One quick call sorts 80 titles; only plausible postings get a full score.
- **Any country, any field.** Country, home area, contracts and CV languages (7 languages) come from the config;
  places are matched with GeoNames; the onboarding interview starts with the country.
- **Review fixes (Oct 2026).** Duplicate sends across boards, one deadline for all career platforms, unscored
  postings that expire.

## Next

1. **One collector, many people.** Today each person runs their own loop, so two people double the scraping. Collect
   once (boards, career pages, archive) and match the shared pool for every person.
2. **Web dashboard.** A small page served by the engine, installable on a phone's home screen: jobs, statuses,
   settings. Telegram stays the notification channel.
3. **More languages and country packs.** Arabic and other CV languages (right-to-left layouts),
   national job APIs beyond France Travail.
4. **Cleaner sources by default.** Official APIs (France Travail, company ATS boards), open data, feeds and alert
   emails first; board scraping only where the board allows it.
5. **Always-on host.** A laptop pauses when its lid closes; a small server or mini PC keeps the loop running.

## Known limits

- Workday job pages already read are fetched again at each poll (wasted requests, no wrong result).
- If Telegram takes the card but not the PDFs, the retry sends the card a second time.
- France Travail's "Offres d'emploi v2" API is granted on request; the national harvest waits for access.

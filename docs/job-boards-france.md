# Job boards and job sources in France

Where job offers in France are published, and how Job Radar can read each source in a legal and respectful way.
Checked on 31 October 2026. Method: the robots.txt of about 110 hosts was fetched with the engine's browser user
agent; live counts were read on the sites that day (one page per site, paced); France Travail partners come from
France Travail's official partner page. Nothing was read past a bot check, captcha, 403 or 429.

## How to read the tables

- **Live offers**: the number the site showed on 31 Oct 2026 ("measured") or its own marketing figure ("claim").
  "n/p": not published.
- **Access**: the respectful route. *API*: official API. *Feed*: RSS or XML published by the site. *JSON-LD*:
  offer pages carry schema.org JobPosting data, a plain-HTML listing links to them, and robots.txt allows both (the
  engine's `jsonld` reader). *Alerts*: alert emails into the alerts mailbox. *Via FT*: offers reach us through the
  France Travail API.
- **Login**: needed to read offers (not to apply).
- **robots.txt**: rules for generic bots (`User-agent: *`). "403": even robots.txt is refused to scripts (bot
  protection), so the site was left alone.
- **FT partner**: on France Travail's official partner list. Partner offers appear on francetravail.fr; they reach
  the API only where the partner agreed to API reuse, so confirm with `origineOffre.partenaires` once the national
  harvest runs.
- **Coverage**: what Job Radar does today.

## Key findings

1. **France Travail is the hub**: 758,396 live offers on 31 Oct 2026, fed by about 150 partner sites (Indeed,
   HelloWork, APEC, Cadremploi, Meteojob, Jobijoba, Talent.com, Direct Emploi, Ouest-France, Staffsanté...), by
   multiposting and ATS vendors (Digital Recruiters, Flatchr, Jobaffinity, Softy, Talentplug, Broadbean, SAP
   multiposting, Beetween, Kioskemploi, Nicoka) and by direct recruiters (Carrefour, EDF, Enedis, E.Leclerc,
   Michelin, Société Générale, Start People, Temporis, the three armies, CNRS). The national harvest is the single
   biggest gain.
2. **Choisir le service public** (54,767 live public-sector offers: State, territorial and hospital) publishes
   official RSS feeds by job family, department, region and employer. robots.txt allows them and the engine already
   has an RSS reader.
3. **Compliance gaps in current coverage**: JobSpy calls endpoints that robots.txt disallows (LinkedIn: everything;
   HelloWork: `/fr-fr/emploi/recherche.html` and every URL with `?`; Glassdoor: `/graph`) and Indeed's mobile API,
   whose terms forbid scraping. HelloWork and Indeed are France Travail partners, so part of their offers can come
   through the API instead.
4. **Leboncoin** forbids automated access in robots.txt ("only permitted with special permission");
   **Ouest-France Emploi** disallows all bots.
5. **Monster.fr closed** on 30 July 2025 (European entities put into liquidation).
6. Most big corporate career sites run on platforms the engine cannot read yet (SuccessFactors, Phenom, iCIMS,
   Taleo, CleverConnect, Digital Recruiters, custom JavaScript sites). Many of their offers reach France Travail
   through multiposting.
7. **Ressources Solidaires** (former ESS job board) now shows a consumer-credit site on its domain: do not use.
8. The big staffing agencies Randstad, Manpower, Synergie, CRIT, Adecco (except Adecco Médical) and Actual are **not**
   France Travail partners: their offers need their own reader.

## 1. Hub and generalist boards

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| France Travail | https://candidat.francetravail.fr/offres/recherche | 758,396 (measured) | API Offres d'emploi v2 (francetravail.io, free app, OAuth client credentials). About 150 results per call and about 1,150 per query (third-party docs), so slice by département, `publieeDepuis`, contract or ROME code | No | Offers allowed; search URLs with `motsCles=` disallowed | Hub | API per search term (`sources.py`); national harvest waits for credentials |
| Indeed | https://fr.indeed.com | n/p | No public search API for third parties; alert emails | No | Search pages allowed; `/viewjob`, `/rc/clk`, alert URLs disallowed | Yes | JobSpy through apis.indeed.com/graphql (against Indeed's terms) |
| LinkedIn | https://www.linkedin.com/jobs | n/p | Alert emails (in use); the Job Posting API is for ATS partners only | No (guest pages) | `Disallow: /` for every unlisted bot | No | JobSpy guest endpoint every 3 h (disallowed) + alerts |
| HelloWork (formerly RegionsJob, ParisJob) | https://www.hellowork.com | 803,084 (measured) | Via FT; alert emails; offer pages are allowed | No | Disallows `/*?` and `/fr-fr/emploi/recherche.html`; offer pages allowed | Yes | JobSpy on the disallowed search page |
| Glassdoor | https://www.glassdoor.fr | n/p | Alert emails | Partly | Disallows `/graph` (JobSpy's endpoint), `/job-listing/*_IE*.htm` | No | JobSpy (against robots.txt and terms) |
| Meteojob | https://www.meteojob.com | 305,820 (measured) | Via FT; alert emails (sender supported, none set up) | No | Disallows `/*?` except `/jobs?*`, `/api/`, `/jobsearch/api/` | Yes | None |
| Direct Emploi | https://www.directemploi.com | 236,453 (measured) | Via FT | No | Offers allowed; `/rss/`, redirects disallowed | Yes | None |
| Leboncoin (emploi) | https://www.leboncoin.fr | n/p | None without written permission | No | "It's forbidden to use search robots or other automatic methods to access Leboncoin.fr" | No | None, keep it that way |
| Keljob / Figaro Emploi | https://emploi.lefigaro.fr (keljob.com redirects there) | n/p | Alert emails | No | 403 | No | None |
| Monster | https://www.monster.fr | 0 | Closed on 30 Jul 2025 | | 403 (redirects to monster.com/fr) | No | None |
| Jobology, Jobvitae, PMEjob, Inzejob, Viteunemploi, Jobinlive | various | n/p | Via FT | No | Jobology permissive | Yes | Via FT once harvested |

## 2. Aggregators and meta-search

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| Jobijoba | https://www.jobijoba.com/fr | n/p (home page shows e.g. 9,167 E.Leclerc and 5,560 O2 offers) | Via FT; partnership | No | Disallows `/fr/rss`, `/fr/query/`, `/fr/redirect/` | Yes | None |
| Talent.com | https://fr.talent.com | n/p | Via FT; publisher program (agreement) | No | Disallows `/search-jobs/*`, `/api/`, `/redirect*` | Yes | None |
| Adzuna | https://www.adzuna.fr | n/p | Official API `api.adzuna.com/v1/api/jobs/fr/search/{page}` (free app_id and app_key, 50 results per page, rate-limited free tier). Read the terms (attribution, caching) | No | Web site answers 403 to scripts | No | None |
| Jooble | https://fr.jooble.org | n/p | REST API key on request (form), meant for sites that display Jooble results | No | 403 | No | None |
| Optioncarrière (Careerjet) | https://www.optioncarriere.com | n/p | Partner API: affiliate ID, and each call must carry the end user's IP and user agent (built for publishers showing results) | No | Disallows `/job/`, `/jobview/`, `/search/rss.html` | No | None |
| Jobrapido | https://fr.jobrapido.com | n/p | None | No | Disallows `/job/*` and query URLs | No | None |
| Google for Jobs | | | Not a source: no public API (it reads the same JobPosting data we read) | | | | |

## 3. Executives and recruitment firms

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| APEC | https://www.apec.fr | 100,000+ "every day" (claim); 549,100 offers published in 2023 | Alert emails (in use: 7 saved searches, read from the email body); via FT | Free account for alerts | 403 (offer pages refuse bots) | Yes | Alerts |
| Cadremploi | https://www.cadremploi.fr | n/p | Alert emails (sender supported, none set up); via FT | Account for alerts | 403 | Yes | None |
| Michael Page / Page Personnel | https://www.michaelpage.fr/jobs (pagepersonnel.fr redirects) | 4,310 (measured) | None today: offer pages carry no JSON-LD | No | Drupal defaults, offers allowed | No | None |
| Hays | https://www.hays.fr | n/p | No marketing category; not checked further | No | Allows `/recherche-emploi/<sector>-offre` | No | None |
| Robert Half | https://www.roberthalf.com/fr/fr/offres-emploi | n/p | None today: no JSON-LD on offer pages | No | Allowed | No | None |
| Robert Walters | https://www.robertwalters.fr | n/p | | | 403 | No | None |
| Expectra / Randstad Professional | https://www.randstadprofessional.fr | n/p | JSON-LD (sector listings `/emploi/<sector>/id=15/`) | No | Allowed | No | **Added**: commercial and marketing listing |
| Uptoo, We Recruit, Adsearch, Talent Detection | | | Via FT | | | Yes | Via FT |

## 4. Startups, tech, IT and freelance

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| Welcome to the Jungle | https://www.welcometothejungle.com/fr | n/p | Job-title pages `/fr/pages/emploi-...` and offer pages (no `?`); alert emails (switched off by WTTJ for now) | No | Disallows `/*?` | No | 16 job-title pages; rests 3 h after its HTTP 202 bot check |
| JobTeaser | https://www.jobteaser.com | n/p | Through a school career-centre account; alerts | Yes (school) | Disallows `/*?*`, allows `/*/job-search/*` | No | None |
| Free-Work (ex Carriere-info, Freelance-info) | https://www.free-work.com | 8,532 freelance missions + 6,090 jobs (measured) | Via FT (Carriere-info.fr is a partner); listings are JavaScript | No | Permissive (`/login`, `/logout` only) | Yes (Carriere-info.fr) | None |
| Station F HAL | https://jobs.stationf.co | n/p | JavaScript app; ask Station F for an export | No | `Allow: /` | No | None |
| LesJeudis | https://lesjeudis.com | n/p (e.g. 1,526 IT project manager offers) | Check JSON-LD before adding | No | Permissive | No | None |
| ChooseYourBoss | https://www.chooseyourboss.com | n/p | | Yes | 403 | No | None |
| Malt | https://www.malt.fr | n/p | Freelance marketplace, missions behind login | Yes | 403 | No | None |
| Codeur.com | https://www.codeur.com/projects | n/p | Freelance projects | Partly | Disallows `/*?*` except `?page=` | No | None |
| LeHibou | https://www.lehibou.com | 5,000+ missions (claim) | Freelance IT missions | Yes | No rules | No | None |

## 5. Students, graduates, alternance, VIE

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| StudentJob | https://www.studentjob.fr | 8,033 (measured) | Not checked further | No | Disallows `/vacatures*`, `/api/`, search URLs | No | None |
| Jobetudiant.net | https://jobetudiant.net | n/p | Not checked further | No | Permissive | No | None |
| 1jeune1solution | https://www.1jeune1solution.gouv.fr | n/p | Public portal for under-26s built on public sources (France Travail, La bonne alternance) | No | Allows `/emplois/`; disallows `/stages/`, `/jobs-etudiants/`, `/emplois-europe/` | n/a | None |
| La bonne alternance | https://labonnealternance.apprentissage.beta.gouv.fr | n/p | Public API on api.apprentissage.beta.gouv.fr (read its docs and token rules) | No | Disallows `/recherche-emploi`, `/espace-pro` | Yes | None for an experienced candidate (excludes alternance) |
| Mon Volontariat International (Business France) | https://mon-vie-via.businessfrance.fr | n/p | VIE and VIA abroad | No | Only `/refresh` disallowed | No | None (VIE excluded) |
| StaffMe, Side, StudentPop | https://www.staffme.fr, https://www.side.co | Side: 10,000+ (claim) | Apps | Yes | Permissive | No | None |

## 6. Interim and staffing agencies

| Agency | URL | Live offers | Engine can read today? | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|
| Randstad | https://www.randstad.fr | 14,262 (measured) | Yes: keyword listings `/emploi/q-<keyword>/` + JSON-LD offers | Allowed (`search=`, `/cdi/`, filters disallowed) | No | **Added**: q-marketing, q-communication |
| Adecco | https://www.adecco.com/fr-fr | 20,000+ (claim) | No: JavaScript listing; `/jobs/`, `/job/` disallowed | Allowed for the listing | Adecco Médical only | None |
| Manpower | https://www.manpower.fr | 13,127 (measured) | No: sector listings exist (communication `s73`, multimedia `s74`) but offer pages carry no JSON-LD | Crawl-delay 10 | No | None |
| Synergie | https://www.synergie.fr | 9,302 (measured) | Yes: sector pages + JSON-LD | Search page disallowed; crawl-delay 1 | No | **Added**: "Édition / Communication / Marketing" sector |
| CRIT | https://www.crit-job.com | 16,000+ (claim) | Yes: keyword listing + JSON-LD | Allow all | No | **Added**: "marketing" keyword listing |
| Actual | https://www.actualgroup.com | 7,471 (measured) | Yes (JSON-LD), but its listings are mostly interim and admin | Allow all; `Content-Signal: ai-train=no` | No | Not added |
| Start People | https://www.startpeople.fr | n/p (300 listing pages) | JSON-LD yes, no category filter in HTML | Drupal defaults | Yes | Via FT |
| Temporis | https://www.temporis-franchise.fr (temporis.fr redirects) | n/p | No JSON-LD | No robots.txt | Yes (also Temporis BTP, Santé, Expert) | Via FT |
| Partnaire | https://www.partnaire.fr | n/p | No: listing in HTML, no JSON-LD | Allow all | No | None |
| Proman | https://www.proman-emploi.fr | n/p | No: JavaScript app | Allow all | No | None |
| Leader Intérim (Groupe Leader) | https://www.leaderinterim.com | n/p | Site unreachable from here on 31 Oct | | No | None |
| Supplay | https://www.supplay.fr | n/p | No offer links on the pages checked | Allow all | No | None |
| Interaction | https://www.interaction-interim.com | n/p | Yes (JSON-LD, 30 newest offers) | Drupal defaults | No | Not added (industrial, naval) |
| Samsic Emploi | https://www.samsic-emploi.fr | n/p | Not confirmed | Filter URLs disallowed | No | None |
| Appel Médical (Randstad group) | https://www.appelmedical.com | n/p | Not checked (same platform as Randstad Professional) | Randstad-style rules | No | None |
| Gojob | https://gojob.com | 50,000+ (claim) | Yes: Lever board | Allow all | Yes | Watched (Lever) |
| Mistertemp' | https://www.mistertemp.com | n/p | Yes: Recruitee board | Allow all | No | Watched (Recruitee) |
| Iziwork, Qapa | https://www.iziwork.com, https://qapa.fr | n/p | Offers on jobs.iziwork.com and jobs.qapa.fr, not checked | Allow all | No | None |

## 7. Public sector

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| Choisir le service public (ex Place de l'emploi public, BIEP) | https://choisirleservicepublic.gouv.fr | 54,767 (measured); 347,200 published in 2025 | **Feed**: `https://place-ep-recrute.talent-soft.com/handlers/offerRss.ashx?LCID=1036` plus filters: `Rss_JobFamily` (29; 3509 Communication, 3510 Culture et Patrimoine, 3522 Numérique), `Rss_JobDepartment` (108), `Rss_JobRegion` (15), `Rss_Entity` (about 5,000 employers), `Rss_Contract`. 20 newest per feed. Offer pages carry JSON-LD. Weekly open data on data.gouv.fr (few fields) | No | Allowed (only `/wp-admin/` and PDF offers disallowed); the feed host has an empty robots.txt | Yes ("PEP") | None |
| Emploi Territorial (CDG network) | https://www.emploi-territorial.fr | n/p | An export exists but robots.txt disallows `/exportoffres/`: ask the FNCDG or a CDG. Territorial offers also reach CSP | No | Disallows `/exportoffres/` | No | None |
| Emploi Collectivités | https://www.emploi-collectivites.fr | n/p | Via FT | No | 403 | Yes | Via FT |
| Profil Public | https://profilpublic.fr | n/p | Recruiting software for public employers; via FT | No | Allow all | Yes | Via FT |
| FHF emploi (public hospitals) | https://emploi.fhf.fr | 10,683 (measured) | None today: no JSON-LD on offer pages. CSP's hospital feed (`Rss_SalaryRange=2457`) covers part | No | Drupal defaults | No | None |
| Hospitals on nous-recrutons.fr | e.g. https://ch-dreux.nous-recrutons.fr | | JSON-LD (the engine reads it) | No | | No | Learned from board apply links |
| Defence: Armée de Terre, Marine nationale, Armée de l'air | | | Via FT (partner recruiters); civilian defence jobs on CSP | | | Yes | Via FT |
| Éducation nationale | | | Contract posts (AESH, teachers) on CSP; exams on devenirenseignant.gouv.fr | | | Via PEP | None |
| CNRS | | | Via FT | | | Yes | Via FT |

## 8. Health, social and care

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| Staffsanté + Staffsocial (Hospimedia group) | https://www.staffsante.fr | 34,846 opportunities (measured) | Via FT | No | No rules | Yes | Via FT |
| Réseau Pro Santé | https://reseauprosante.fr | about 500 (site title) | Via FT | No | Offers allowed | Yes | Via FT |
| MStaff | https://www.mstaff.co | n/p | Via FT | No | Only the first 5 listing pages allowed | Yes | Via FT |
| Hublo | https://hublo.com | | Staffing software for hospitals, no public board | | Allow all | No | None |
| Appel Médical, Adecco Médical | | | Adecco Médical via FT | | | Adecco Médical: yes | |
| Dentalemploi, Club Officine, Teamofficine, Sanitaire et social, Crechemploi, La Maison Bleue, Kinougarde | | | Via FT | | | Yes | Via FT |

## 9. Hospitality and restaurants

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| L'Hôtellerie Restauration | https://www.lhotellerie-restauration.fr/emploi/ | 1,886 (measured); 50,000+ a year (claim) | Check JSON-LD before adding | No | Offers allowed | No | None |
| Hosco | https://www.hosco.com | 340+ new a week (claim) | | To apply | Crawl-delay 10 | No | None |
| Cookorico | https://www.cookorico.com | n/p | Via FT | | TLS error from here | Yes | Via FT |
| Gestion Camping | | | Via FT | | | Yes | Via FT |
| Extracadabra | https://www.extracadabra.com | 800 to 1,300 a day (claim) | App | Yes | `/api/` disallowed | No | None |
| Brigad | https://www.brigad.co | missions | Freelance app | Yes | Filter URLs disallowed | No | None |
| Accor, Barrière, Louvre Hotels, Mama Shelter | SmartRecruiters boards | | Yes | | | No | Watched |

## 10. Construction, industry, energy, environment

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| Batiactu (emploi) | https://www.batiactu.com | n/p | Via FT | | Crawl-delay 1 | Yes | Via FT |
| FFB regional boards (12 regions) | | | Via FT | | | Yes | Via FT |
| Le Moniteur, Construction et Talents | https://www.lemoniteur.fr/construction-et-talents/ | n/p | Not checked | | | No | None |
| L'industrie recrute (UIMM) | https://www.lindustrie-recrute.fr | n/p | Via FT | | HTTP 202 bot check: left alone | Yes | Via FT |
| Aerocontact | https://www.aerocontact.com | n/p | Via FT | | Detail pages and filtered queries disallowed | Yes | Via FT |
| Energie Recrute, Emploi Environnement, Clicandpower, Clicandearth, Clicandsea | https://www.emploi-environnement.com | n/p | Via FT | | Emploi Environnement permissive | Yes | Via FT |

## 11. Transport and logistics

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| Jobtransport | https://www.jobtransport.com | 14,278 (measured) | Via FT | No | Filtered queries disallowed | Yes | Via FT |
| Gojob, Iziwork, Qapa | see staffing | | | | | Gojob: yes | Gojob watched |

## 12. Retail, fashion, beauty

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| Distrijob | https://www.distrijob.fr | n/p | Via FT | | Timed out from here | Yes | Via FT |
| Beautéjob | https://www.beautejob.com | n/p | Via FT | | Connection reset from here | Yes | Via FT |
| Fashionjobs | https://www.fashionjobs.com | n/p | Not checked | | No robots.txt | No | None |
| Retail employers | | | Carrefour, E.Leclerc, Marie Blachère, Celio via FT; Kiabi (SmartRecruiters, added); METRO (watched); Auchan and Leroy Merlin (CleverConnect, not readable); Decathlon (Digital Recruiters); Fnac Darty (Talentsoft feed) | | | Partly | |

## 13. Agriculture and wine

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| ANEFA | https://www.anefa-emploi.org | n/p (maintenance page on 31 Oct) | Via FT | No | Permissive | Yes | Via FT |
| APECITA | https://www.apecita.com | 21,000+ a year (claim) | Via FT | No | Allowed | Yes | Via FT |
| Jobagri | | | Via FT | | | Yes | Via FT |
| Vitijob (Vitisphere) | https://www.vitijob.com | 10,000+ a year (claim) | Via FT | No | Filtered queries disallowed | Yes | Via FT |

## 14. Culture, media, music

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| ProfilCulture | https://www.profilculture.com | n/p | Category pages (no JSON-LD; fixed page layout) | No | No robots.txt | No | 4 categories watched |
| CSP Communication and Culture et Patrimoine feeds | see public sector | | Feed (`Rss_JobFamily=3509`, `3510`) | No | Allowed | Yes | None |
| CNM (Centre national de la musique) | https://cnm.fr | | Posts its jobs on CSP | | | Via PEP | Via CSP once fed |
| Stratégies emploi (marketing, media) | | | Board feed (`rss_board` reader being added) | | | | In progress |
| Music employers | | | Universal Music France and Warner Music (Workday), Sony Music (Greenhouse), Believe (SmartRecruiters), Deezer (Teamtailor), Spotify (Lever), Live Nation (Workday), AEG (Greenhouse), Kobalt (Workable) | | | No | Watched |
| Media employers | | | France Télévisions (SuccessFactors), Radio France, TF1, Canal+, M6: career pages not readable or not found | | | No | None |

## 15. NGOs, impact, disability

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| Jobs that make sense | https://jobs.makesense.org | 5,449 (measured) | JSON-LD on offers, but the HTML listing shows only 5; alert emails (sender supported) | No | Offers allowed | No | None |
| Coordination SUD | https://www.coordinationsud.org | n/p | Offers page not found at `/offres-emploi/` | | Permissive | No | None |
| ReliefWeb | https://reliefweb.int | | Official API (international humanitarian jobs) | No | Allowed | No | None |
| UDES (social economy employers) | | | Via FT | | | Yes | Via FT |
| Ressources Solidaires | https://www.ressources-solidaires.org | | Domain now shows a consumer-credit site: do not use | | | No | None |
| Handicap.fr, Handicap Job, Talents Handicap | https://emploi.handicap.fr | 25,000+ (claim) | Via FT | No | Allow all | Yes | Via FT |
| Service Civique | https://www.service-civique.gouv.fr | | Civic-service missions, not jobs | No | All allowed | No | None |

## 16. Regional and cross-border

| Source | URL | Live offers | Access (respectful) | Login | robots.txt | FT partner | Coverage |
|---|---|---|---|---|---|---|---|
| Ouest-France Emploi | https://emploi.ouest-france.fr (ouestfrance-emploi.com redirects) | n/p | Via FT only | No | `Disallow: /` for all bots | Yes | Via FT |
| Moovijob (Grand Est, Luxembourg) | https://www.moovijob.com | n/p | Via FT | | 403 | Yes | Via FT |
| Emploi LR, L'Aveyron recrute, Bretagne alternance, Cap Métiers Nouvelle-Aquitaine, Domemploi, Layan, Cyphoma (overseas) | | | Via FT | | | Yes | Via FT |

## 17. Other niche France Travail partners

Dogfinance (finance), Lamacompta (accounting), Recrutimmo (real estate), Village de la justice (legal), Équi-ressources
and EQUEST (equestrian), Fédération Nationale Profession Sport et Loisirs, OPCO Atlas, Yoopies, Aladom, Happycab, Momji,
Complétude, Jeanbauche, Wink, Oxilia, Savoir pour faire, Transentreprise and Cessionpme (business transfer),
CarriereOnline, Candiquest, Accelerh, Mangeons Frais, Provenc'Hall, Dalkia, Enedis, Conseil Régional Pays de la Loire.
All reach us through the France Travail harvest.

## 18. Career-site platforms (the company layer)

| Platform | Examples seen | Engine reads today | Respectful method | FT partner |
|---|---|---|---|---|
| Lever, Greenhouse, Ashby, Workable, SmartRecruiters, Teamtailor, Recruitee, Personio | about 230 boards watched | Yes | Public job-board APIs and feeds | No |
| Workday | 35 boards (Airbus, Chanel, Michelin, Renault, Thales, Sanofi, Pernod Ricard...) | Yes | The JSON endpoint the career pages use | No |
| Talentsoft (Cegid) | Air France, Crédit Agricole (casa-recrute), Fnac Darty, Framatome, CSP | Feed reader exists; `companies add` cannot add feed URLs yet | `/handlers/offerRss.ashx?LCID=1036` | No |
| nous-recrutons.fr | hospitals, Spartoo, UPEC | Yes (JSON-LD) | Home page lists offers | No |
| SAP SuccessFactors | Alstom, Engie, TotalEnergies, France Télévisions, Bouygues Construction, Colgate, SKF | No: offer pages use schema.org microdata, not JSON-LD | Server-rendered `/search/` pages + microdata. The RSS under `/services/` is disallowed by robots.txt | SAP multiposting: yes |
| Taleo (Oracle) | Société Générale | Partly: careers.societegenerale.com offer pages carry JSON-LD, the home page lists only 5 | | |
| iCIMS | AXA France, Publicis, Expleo | No | | |
| Phenom | Orange, Thales (front end) | No (JavaScript) | Thales is read through its Workday back end | |
| Beamery | Sanofi (front end) | Read through its Workday back end | | |
| CleverConnect | Auchan, Leroy Merlin | No | | |
| Digital Recruiters (Cegid) | Decathlon | No (JavaScript listing) | Via FT when multiposted | Yes |
| Flatchr, Jobaffinity, Softy, Beetween, Altays, Nicoka, Candidatus, Chaze.io, Kioskemploi, Talentplug, Broadbean | SMEs | No | Via FT when multiposted | Yes |
| Gestmax, Oracle Recruiting Cloud | Ouest-France, CHD Vendée; Edel | No | | |

## 19. Big employers

| Employer | Career site | Platform found | Readable today | Status (31 Oct) | FT partner |
|---|---|---|---|---|---|
| SNCF | https://www.sncf.com/fr/groupe/emploi | DataDome captcha on any scripted visit | No | Left alone | No |
| La Poste | https://recrutement.lapostegroupe.com | Custom, JavaScript listing | No | | No |
| Orange | https://orange.jobs | Phenom | No | | No |
| Carrefour | recrute.carrefour.fr (did not resolve from here) | not checked | | Via FT | Yes |
| Auchan | https://www.auchan-recrute.fr | CleverConnect | No | | No |
| LVMH | https://www.lvmh.com/en/join-us/our-job-offers | JavaScript site; plus a SmartRecruiters board (4 Paris e-commerce jobs) | SmartRecruiters: yes | **Added** (SmartRecruiters) | No |
| L'Oréal | https://careers.loreal.com | Custom | No | | No |
| BNP Paribas | https://group.bnpparibas | Akamai 403, even on robots.txt | No | Left alone | No |
| Société Générale | https://careers.societegenerale.com | Taleo; JSON-LD offer pages | Partly | Not added (via FT) | Yes |
| AXA | https://recrutement.axa.fr | iCIMS | No | | No |
| Accor | https://careers.accor.com | SmartRecruiters `AccorHotel` (888 France jobs) and `AccorCorpo` (115) | Yes | Already watched, but shown as "Mama Shelter" and "Adagio Aparthotel" | No |
| Decathlon | https://joinus.decathlon.fr | Digital Recruiters | No | | Through DR |
| Leroy Merlin | https://recrute.leroymerlin.fr | CleverConnect | No | | No |
| Airbus | Workday `ag.wd3/Airbus` | Workday | Yes | Already watched | No |
| Thales | https://thales.wd3.myworkdayjobs.com/Careers | Workday (Phenom front end) | Yes | **Added** | No |
| Capgemini | https://www.capgemini.com/fr-fr/carrieres/ | Custom, JavaScript | No | | No |
| Sopra Steria | SmartRecruiters `SopraSteria1` | SmartRecruiters | Yes | Already watched | No |
| EDF | https://www.edf.fr/edf-recrute | Custom, JavaScript | No | Via FT | Yes |
| Engie | https://jobs.engie.com | SuccessFactors | No | | No |
| Veolia | https://jobs.veolia.com | Custom, JavaScript | No | | No |
| Bouygues Construction | https://careers.bouygues-construction.com | SuccessFactors | No | | No |
| Vinci | https://jobs.vinci.com | Custom, JavaScript | No | | No |
| Sanofi | https://sanofi.wd3.myworkdayjobs.com/SanofiCareers | Workday (937 jobs, 156 in France) | Yes | **Added** | No |
| Pernod Ricard | https://pernodricard.wd3.myworkdayjobs.com/pernod-ricard | Workday (302 jobs, 153 in France) | Yes | **Added** (watchlist name "Pernodricard": rename) | No |
| Kiabi | https://jobs.smartrecruiters.com/Kiabi | SmartRecruiters (119 France jobs) | Yes | **Added** | No |
| Kering | Workday `kering.wd3/Kering` | The Workday site returns 0 jobs | | Not added | No |
| Accenture | Workday `accenture.wd103/AccentureCareers` | Postings carry no location text, so the reader would drop them | | Not added | No |
| Air France, Crédit Agricole, Fnac Darty | Talentsoft | Feed | Reader yes, `companies add` no | Pending | No |
| Alstom, TotalEnergies, France Télévisions | SuccessFactors | | No | | No |
| Publicis | https://careers.publicisgroupe.com | iCIMS | No | | No |
| Michelin, Enedis, Dalkia, E.Leclerc, Marie Blachère, Celio | | | | Via FT (Michelin and Celio also watched) | Yes |
| Saint-Gobain, Safran, Sephora, Schneider Electric, Bureau Veritas, Stellantis, PwC | | 403 or Akamai | | Left alone | No |

## 20. Next to integrate (ranked by new offers per effort)

1. **France Travail national harvest.** Up to 758,396 live offers, every city and sector, including partner offers
   that consented to API reuse. Effort: low to medium, credentials pending. Slice queries to stay under the
   per-query cap (département x `publieeDepuis=1`, then contract type or ROME code when a slice is full), keep a
   daily delta, store `origineOffre.partenaires` to learn which boards flow in. Official API: read its terms before
   showing offers to third parties.
2. **Choisir le service public feeds.** 54,767 live public jobs, about 950 new a day (347,200 in 2025). Effort: low
   (the RSS reader exists). Poll the 108 department feeds for full coverage, or job-family feeds for a candidate
   (e.g. Communication 3509, Culture et Patrimoine 3510, Numérique 3522). Official feeds, robots.txt allows them.
3. **Talentsoft feeds of big employers** (Air France, Crédit Agricole, Fnac Darty; more are learned from apply
   links). Effort: very low: let `companies add` route `*.talent-soft.com` URLs to the `rss` reader.
4. **Microdata in the JSON-LD reader** to read SuccessFactors sites through their allowed `/search/` pages (Alstom,
   Engie, TotalEnergies, Bouygues Construction, France Télévisions, Colgate, SKF...). Effort: low to medium.
5. **More ATS boards of big employers** (Workday, SmartRecruiters). Five added today. Effort: very low, ongoing.
6. **Staffing agencies by keyword or sector** (Randstad, Synergie, CRIT, Expectra added today; Actual, Interaction,
   Start People possible). These agencies are mostly not France Travail partners. Effort: very low.
7. **Adzuna API** (official, free key, France supported): aggregator coverage beyond France Travail, not measured.
   Effort: low. Read the terms first (attribution, caching, display).
8. **Alert emails for boards that refuse bots**: Cadremploi, Indeed, HelloWork, Meteojob, Glassdoor, Jobs that make
   sense, JobTeaser (through a school), Welcome to the Jungle when its alerts return. Effort: account setup only.
9. **Emploi Territorial export**: robots.txt disallows `/exportoffres/`, so ask the FNCDG or a CDG. Low priority:
   territorial offers already reach CSP.
10. **Jooble, Careerjet, Talent.com, Jobijoba programs**: publisher or partner agreements written for sites that
    display results to their own users; much of their content already reaches France Travail. Low.

## 21. Do not automate

- **Leboncoin**: robots.txt forbids automated access without permission.
- **LinkedIn**: robots.txt `Disallow: /` for unlisted bots; terms forbid scraping. Today's JobSpy use breaks both;
  alert emails are the respectful route.
- **Indeed**: terms forbid scraping; robots.txt disallows `/viewjob`. Its partner offers can come through France Travail.
- **Glassdoor**: robots.txt disallows `/graph`, the endpoint JobSpy uses; terms forbid scraping.
- **HelloWork search**: `/fr-fr/emploi/recherche.html` and every `?` URL are disallowed (JobSpy uses them). Offers
  reach France Travail; alerts work.
- **Ouest-France Emploi**: `Disallow: /` for all bots.
- **403, captcha or bot check, left alone**: APEC, Cadremploi, Figaro Emploi (Keljob), Jooble and Adzuna web sites,
  Moovijob, Malt, ChooseYourBoss, Emploi Collectivités, Robert Walters, SNCF (DataDome captcha), BNP Paribas,
  Stellantis, PwC (Akamai), Saint-Gobain, Safran, Sephora, Schneider Electric, Bureau Veritas, L'industrie recrute
  (HTTP 202).
- **SuccessFactors RSS** under `/services/`: disallowed by robots.txt (checked on Alstom).
- **Legal flag** (the operator's call): where robots.txt allows, French law still protects databases (sui generis right,
  Code de la propriété intellectuelle art. L342-1); repeated extraction of a substantial part of a board's offers can
  be challenged. APIs, published feeds and partner agreements avoid that risk.

## 22. Needs the operator

1. France Travail credentials (in progress) and a read of the API terms.
2. A free Adzuna developer account, if wanted, plus its terms.
3. Alert accounts pointed at the alerts mailbox: Cadremploi, Indeed, HelloWork, Meteojob, Jobs that make sense;
   JobTeaser through a school account.
4. A decision on JobSpy's LinkedIn, Indeed, Glassdoor and HelloWork searches (robots.txt and terms, above).
5. Optional partner requests: FNCDG (Emploi Territorial export), Leboncoin (permission), Talent.com or Jobijoba feeds.
6. For whoever edits the code: rename "Pernodricard" to Pernod Ricard and the two Accor boards ("Mama Shelter" is
   AccorHotel, "Adagio Aparthotel" is AccorCorpo); let `companies add` accept Talentsoft and other feed URLs; add
   microdata to the JSON-LD reader; Workday boards whose postings lack `locationsText` (Accenture) are dropped.

## 23. Added to the watchlist on 31 Oct 2026

Each was checked first (API answer, or listing plus one offer page with JobPosting data):

| Board | URL | Reader | What it showed |
|---|---|---|---|
| Pernod Ricard | https://pernodricard.wd3.myworkdayjobs.com/pernod-ricard | Workday | 302 jobs, 153 in France |
| Thales | https://thales.wd3.myworkdayjobs.com/Careers | Workday | 2,000+ jobs; France search full |
| Sanofi | https://sanofi.wd3.myworkdayjobs.com/SanofiCareers | Workday | 937 jobs, 156 in France |
| Kiabi | https://jobs.smartrecruiters.com/Kiabi | SmartRecruiters | 119 France jobs (stylist, retail) |
| LVMH | https://jobs.smartrecruiters.com/LVMH | SmartRecruiters | 4 Paris jobs (e-merchandising, online buyer) |
| Randstad, marketing | https://www.randstad.fr/emploi/q-marketing/ | JSON-LD | 31 offers (chef de produit marketing, assistant marketing) |
| Randstad, communication | https://www.randstad.fr/emploi/q-communication/ | JSON-LD | 30 offers (chargé de communication digitale, chef de projet événementiel) |
| Expectra (Randstad Professional) | https://www.randstadprofessional.fr/emploi/commercial_marketing/id=15/ | JSON-LD | 39 offers |
| Synergie | https://www.synergie.fr/trouver-un-emploi/secteurs/edition-communication-marketing | JSON-LD | assistant marketing, commercial B2B |
| CRIT | https://www.crit-job.com/offres?motsClefs=marketing | JSON-LD | 20 offers (assistante communication, analyste de marché) |

## Sources

- France Travail partner list: https://www.francetravail.fr/candidat/vos-services-en-ligne/des-partenaires-pour-vous-propos.html
- France Travail live count: https://candidat.francetravail.fr/offres/recherche
- France Travail offers dataset (statistics): https://www.data.gouv.fr/datasets/offres-demploi-diffusees-a-france-travail
- France Travail API limits (third-party): https://jobspipe.dev/blog/france-travail-api and https://pypi.org/project/france-travail-job-offers/0.1.0/
- Choisir le service public: https://choisirleservicepublic.gouv.fr/nos-offres/ ; feeds: https://place-ep-recrute.talent-soft.com/offre-de-emploi/tous-les-flux-rss.aspx ; open data: https://www.data.gouv.fr/datasets/les-offres-diffusees-sur-choisir-le-service-public ; 2025 volume: https://www.fonction-publique.gouv.fr/toutes-les-publications/le-nombre-doffres-publiees-sur-le-site-choisir-le-service-public-se-stabilise-en-2025 ; employer-side API: https://choisirleservicepublic.gouv.fr/wp-content/uploads/2026/08/Documentation-API-CSP.pdf
- Monster closure: https://www.blog-rh.com/2025/08/fermeture-monster-fr/ and https://www.lemondeinformatique.fr/actualites/lire-une-trentaine-d-emplois-menaces-par-la-fin-du-site-de-recrutement-monster-97556.html
- APEC figures: https://www.apec.fr/qui-sommes-nous.html and https://corporate.apec.fr/files/live/sites/corporate/files/Notre%20Vision/pdf/rapport-financier-2023
- Jooble API: https://in.jooble.org/api/about
- Careerjet API: https://github.com/careerjet/careerjet-api-client-python and https://jobspipe.dev/blog/careerjet-api
- Adzuna API (third-party description; official terms at https://developer.adzuna.com): https://glama.ai/mcp/servers/@folathecoder/adzuna-job-search-mcp
- Thales on Workday: https://www.thalesgroup.com/fr/group/press_release/thales-recrute-11-000-talents-le-monde-4-000-france-inventer-prochaines
- Staffsanté and Hospimedia: https://my.motherbase.ai/company/153341-staffsantestaffsocial
- Leboncoin robots.txt: https://www.leboncoin.fr/robots.txt

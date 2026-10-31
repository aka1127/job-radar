# Job alert emails (10 minutes, optional but worth it)

Many boards cannot be searched politely (LinkedIn blocks frequent searches, Indeed's robots.txt forbids its offer
pages, some answer bots with 403), but almost all of them email their alerts, in every country. Point those alerts at one
mailbox: the engine reads it every hour (IMAP, never marking anything as read) and treats each job like any other
(filter, triage, score, tailored pack in Telegram).

## 1. A mailbox

Best: a new Gmail just for alerts, so the candidate's inbox stays clean. A label in an existing Gmail also works:
add a filter that puts the alerts under it and set that label as the folder in step 3.

## 2. An app password (never the real password)

1. In that Google account: Security, turn on 2-Step Verification.
2. Search "App passwords" in the account settings, create one named "Job Radar", copy the 16 letters.

## 3. Tell the engine

Add these lines to `.env` (no quotes, no spaces around "="):

    ALERTS_IMAP_USER=your.alerts.mailbox@gmail.com
    ALERTS_IMAP_PASSWORD=the 16 letters, without spaces

Optional: `ALERTS_IMAP_FOLDER=Job alerts` to read one Gmail label only; `ALERTS_IMAP_HOST=` for a mailbox that is not
Gmail; a `_<NAME>` suffix (`ALERTS_IMAP_USER_ALEX`) for one candidate only. Then check:

    python -m hunter doctor

It should say "job alert mailbox: connected". The running loop picks it up at its next cycle.

## 4. Alerts that send to that mailbox

Daily alerts with the searches that matter, home area first, the contracts wanted.

**Any country**: LinkedIn (job search, "Set alert", daily email) and Indeed (search, then the alert form under the
results). Local boards whose emails link to their offers work too when their offer pages carry schema.org
`JobPosting` data; otherwise add a reader for them in `hunter/alerts.py` (see the ones below).

**France**, readers included:


| Board | How | What the engine does with the email |
|---|---|---|
| APEC | free account, search, "Créer une alerte" | reads each offer from the email itself (offer pages answer 403) |
| Cadremploi | Mes alertes, "Créer une alerte" (title, place, contracts) | reads each offer from the email (403 to bots) |
| HelloWork | search, "Créer mon alerte" (title from its list) | opens the offer page: full posting (JobPosting data) |
| Meteojob | profile wishes (job titles, places, contracts) + daily "matching" alert | opens the offer page: full posting |
| Indeed | search with filters, "Activer" under the results | reads each offer from the email (robots.txt forbids offer pages) |
| LinkedIn | job search, "Set alert", daily email | reads each job through its public page |
| Welcome to the Jungle | search, "Créer une alerte" (when their alerts are on) | opens the offer page |

Only emails from known job boards are read, and only their job links are opened. Offers read from the email carry
a line on their card saying to open the full posting before applying.

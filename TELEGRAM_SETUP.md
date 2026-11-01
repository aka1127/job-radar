# Telegram bot setup (5 minutes)

Telegram is the engine's phone app: every good match arrives there with its CV, letter and messages, and the
buttons under each job track what happened next.

1. In Telegram, search for @BotFather (the one with the blue check), open it, tap Start.
2. Send `/newbot`, give it a name (e.g. `Job Radar`) and a username ending in `bot` (e.g. `alex_jobradar_bot`).
3. BotFather replies with a token like `1234567890:AAH...xyz`. Copy it.
4. Open `.env` (copy `.env.example` first) and paste it after `TELEGRAM_BOT_TOKEN=`, no spaces, no quotes.
5. Run `python -m hunter telegram --who alex`, open the bot in Telegram and tap Start. The command shows who wrote
   to the bot (name, username, chat id) and asks you to confirm before it connects that chat: the bot's username is
   public, and the CVs must reach the right phone.

Never share the token: anyone with it can send messages as the bot.

Running it for someone else? Test it on your own chat first, then run
`powershell -ExecutionPolicy Bypass -File .\scripts\handover.ps1 -Who alex` and have them press Start in the bot
within 10 minutes. It forgets the test jobs so they get every good match fresh, connects their chat, keeps yours
as the admin chat (errors come to you, jobs go to them) and restarts the hunter.

## What arrives for each job

Three messages per job, so jobs stand apart when you scroll:
1. A header picture in the company's colors with its logo, "NEW JOB" (or "YOUR LINK" for a link you sent; jobs in
   the candidate's priority sector get one fixed look, e.g. "HEALTH · PRIORITY"), the company, the role and the fit
   score. Under it, the short card: place, contract, how fresh, why it fits, gaps, ATS and screener scores, a
   "Check before sending" line only when something needs a look, and the buttons I applied / Not for me. Every
   sentence can be reworded or translated in `config.yaml` (`texts:`).
2. The CV and the cover letter (PDF), named like a person would: `Alex-Moreau-CV-Company.pdf`.
3. The LinkedIn note and the message for once they accept, ready to copy, with the interview prep collapsed
   underneath.

A week after "I applied", the follow-up message arrives on its own. After applying, tap "Got an interview", "Got an
offer" or "Rejected" under the job; a summary arrives every Monday morning. Jobs applied through Workday, Taleo and
similar portals come with a Word CV (.docx) instead of the PDF, because those portals read Word best.
Send the bot any job link to get a pack for it; `/status` shows the counts and today's Claude usage.

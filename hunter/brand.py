"""One place for the look and the words of the product.

`brand:` in config.yaml (name, colors, the priority look, the font) and `texts:` (every sentence the person reads in
Telegram, by key) override the defaults below; a candidate's config.yaml can override them again. Candidate()
calls configure(); the renderer, the templates, the Word CV, the logos, notify, bot and the pipeline read brand(),
theme() and text(). Rebrand here, not in the code."""
import copy

BRAND = {
    "name": "Job Radar",
    "accent": "#2453c9",      # CV and letter accent when the target company gives no color
    "accent_ink": "#1b3e99",  # darker accent: employer names, dates, Word headings
    "soft": "#f2f5fb",        # tinted backgrounds: header band, tiles
    "badge": "#1e3a8a",       # monogram badge for employers and schools without a logo
    "font": "Inter",          # family name of the woff2 files in assets/fonts (with their .range files)
    "priority": {             # the Telegram header of a job in the priority sector, whatever the company's colors
        "gradient": ["#14061f", "#4a0f5c", "#b0125f"], "tag": "#f5c542", "tag_ink": "#2a0c33"},
}

TEXTS = {
    # Telegram header picture
    "tag_new": "NEW JOB", "tag_link": "YOUR LINK", "tag_priority": "{tag} · PRIORITY", "fit": "FIT",
    # the card under the picture
    "priority_head": "{emoji} <b>{label} · PRIORITY</b>", "priority_label": "PRIORITY SECTOR",
    "outside": " (outside {home})", "posted_today": "posted today", "posted_yesterday": "posted yesterday",
    "posted_days": "posted {days} days ago",
    "cv_scores": "• 📄 CV in {lang} · ATS {ats} · screener {screener}",
    "word_cv": "• 📝 Word CV: {portal} reads Word best, upload the .docx", "this_portal": "this portal",
    "summary_only": "• ℹ️ Built from the alert email's summary: read the full posting before applying",
    "check_before": "• ❗ <b>Check before sending:</b> {flags}", "apply": "Apply", "find_manager": "Find the hiring manager",
    # the messages to copy, and the collapsed interview prep
    "note": "💬 <b>LinkedIn note</b>, with the invitation", "message": "✉️ <b>Message once they accept</b>",
    "who": "👤 Who: {titles}", "prep": "🧭 <b>Interview prep</b>", "prep_news": "News", "prep_idea": "Idea",
    "prep_ask": "Ask", "prep_say": "Say", "prep_missing": "Not in the CV (add to the profile only if true)",
    # buttons and their labels once pressed
    "btn_applied": "✅ I applied", "btn_not_for_me": "🙅 Not for me", "btn_undo": "↩️ Undo",
    "btn_interview": "🎤 Got an interview", "btn_rejected": "❌ Rejected", "btn_offer": "🎉 Got an offer",
    "btn_followed_up": "✅ Follow-up sent", "label_applied": "✅ Applied", "label_skipped": "🙅 Skipped",
    "label_interview": "🎤 Interview", "label_rejected": "❌ Rejected", "label_offer": "🎉 Offer",
    # the bot
    "help": ("Hi! I watch job boards and company career pages and send you a tailored CV, cover letter and "
             "outreach messages for every good match.\n\n"
             "• Tap <b>I applied</b> under a job to track it: a week later I send you the follow-up to copy.\n"
             "• Then tap <b>Got an interview</b>, <b>Got an offer</b> or <b>Rejected</b>: it shows what works.\n"
             "• Send me <b>any job link</b> and I build the pack for it.\n"
             "• /status shows the numbers; a short summary comes every Monday."),
    "connected": "✅ Connected. Job packs for <b>{name}</b> will arrive here.",
    "reply_applied": "Tracked ✅ A week from now you get the follow-up to send.", "reply_not_for_me": "Got it, skipped.",
    "reply_followed_up": "Nice, follow-up logged.", "reply_interview": "🎤 Well done! The interview prep is under the job.",
    "reply_rejected": "Logged. On to the next one.", "reply_offer": "🎉 Congratulations!", "reply_undone": "Undone.",
    "not_tracked": "This job is no longer tracked.",
    "status": ("📊 <b>Status</b>\n• Jobs sent to you: {total}\n• Applied: {applied}\n"
               "• Interviews: {interviews} · Offers: {offers} · Rejected: {rejected}\n• Not for me: {not_for_me}\n"
               "• Good matches waiting: {queued}\n• Career pages watched: {companies}\n• Claude calls today: {calls}"),
    "on_it": "On it: building the pack for this job. It takes a few minutes.",
    "send_link": "Send me a job link, or /status.", "link_failed": "Sorry, that one failed: {error}",
    "link_unreadable": "Could not read a job posting at that link.",
    # a week later, and every Monday
    "followup": ("⏰ <b>Follow-up time</b>: {title} · {company}\nYou applied {days} days ago. Send this to the person "
                 "you contacted (or reply to your application email):\n<pre>{text}</pre>"),
    "weekly_title": "📊 <b>Your week</b> ({start} to {end})", "weekly_sent": "• Jobs sent: {n}{by_source}",
    "weekly_outcomes": "• Applied: {applied} · Interviews: {interviews} · Offers: {offers} · Rejected: {rejected}",
    "weekly_best": "• Waiting for your decision: {n}. Best: <b>{title} · {company}</b> ({score}/100)",
    "weekly_since": "• Since the start: {interviews} interview{s1} from {applied} application{s2} ({rate}%)",
    "source_links": "your links", "source_company_sites": "company sites",
    # warnings for whoever runs the engine (the admin chat when there is one)
    "alert": "⚠️ {text}",
    "alert_paused": ("The hunter was paused for about {hours} hours (PC asleep, lid closed or the program stopped). "
                     "It is catching up now: no job from that time is lost."),
    "alert_pack_failed": "Pack failed: {title} | {company}\n{error}",
    "alert_usage": "Claude usage: {calls} calls today (heads-up threshold {limit}). Nothing is blocked; see python -m hunter usage.",
    "alert_limit": "Claude usage limit reached: the hunter pauses for {minutes} min, then carries on.",
    "alert_cycle_failed": "A cycle failed and will retry in 10 min: {error}",
    "alert_code_broken": "New code does not compile, the hunter keeps the running version: {error}",
    # email delivery, the pack.md text and the local dashboard
    "email_subject": "[{score}] {title} | {company}",
    "brief_news": "News", "brief_snapshot": "Snapshot", "brief_ideas": "Ideas for the first 90 days",
    "brief_questions": "Questions to ask", "txt_note": "LINKEDIN NOTE", "txt_message": "MESSAGE TO THE HIRING MANAGER",
    "txt_followup": "FOLLOW-UP (one week after applying)", "txt_who": "WHO TO CONTACT", "txt_angles": "INTERVIEW ANGLES",
    "txt_letter": "COVER LETTER", "txt_brief": "COMPANY BRIEF", "dashboard_title": "{name}: applications",
}

_brand: dict = copy.deepcopy(BRAND)
_texts: dict = dict(TEXTS)


def configure(cfg: dict | None):
    """Apply `brand:` and `texts:` of a loaded config (the engine's, merged with the candidate's)."""
    global _brand, _texts
    merged = copy.deepcopy(BRAND)
    for k, v in ((cfg or {}).get("brand") or {}).items():
        merged[k] = merged[k] | v if isinstance(v, dict) and isinstance(merged.get(k), dict) else v
    _brand = merged
    _texts = TEXTS | {k: str(v) for k, v in ((cfg or {}).get("texts") or {}).items()}


def brand() -> dict:
    return _brand


def theme() -> dict:
    """The default CV and letter palette (used when the target company gives no color)."""
    return {"accent": _brand["accent"], "accent_ink": _brand["accent_ink"], "soft": _brand["soft"]}


def text(key: str, **kw) -> str:
    """A sentence the person reads, with its placeholders filled."""
    template = _texts[key]
    return template.format(**kw) if kw else template

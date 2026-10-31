"""What reaches Telegram: valid HTML, short, in order, and nothing lost when Telegram has a bad moment."""
import json

import pytest

from conftest import telegram_html_errors
from hunter import notify, pipeline
from hunter.store import Store, short_id

TRICKY = 'R&D <team> "quoted" l\'équipe · 20% · émoji 🚀'
JOB = {"id": "linkedin:li-1", "site": "linkedin", "title": f"Chargé(e) marketing {TRICKY} (H/F)",
       "company": "Société & Fils", "location": "Paris, Île-de-France, France", "posted": "2026-10-29",
       "url": "https://example.com/job?a=1&b=2", "apply_url": "", "description": "x" * 300}
FIT = {"score": 81, "why_fit": ["CRM & automation", "B2B <lead gen>", "French + English"],
       "gaps": ["Salesforce admin"], "contract": "CDI", "language": "fr", "location_type": "home_region"}
PACK = {"linkedin_note": f"Bonjour, {TRICKY}", "hiring_manager_message": "Bonjour [Prénom],\n\nMerci & à bientôt <3",
        "hiring_manager_titles": ["Head of Growth", "CMO"], "interview_angles": [f"Angle {TRICKY}"] * 3,
        "follow_up": "Bonjour, je me permets de revenir vers vous & ...", "cover_letter": "Madame, Monsieur,"}
BRIEF = {"what_they_do": f"They sell {TRICKY}", "recent_news": ["News <1>", "News & 2"], "ideas": ["Idea"] * 3,
         "questions": ["Q?"] * 3, "website": "example.com"}


def res(tmp_path, **kw):
    pdf, letter = tmp_path / "Alex-Moreau-CV-X.pdf", tmp_path / "Alex-Moreau-Lettre-X.pdf"
    pdf.write_bytes(b"%PDF-1.4 cv")
    letter.write_bytes(b"%PDF-1.4 letter")
    return {"pdf": pdf, "letter_pdf": letter, "pack": PACK, "brief": BRIEF, "lang": "fr", "tier": 1,
            "ats": {"score": 97, "missing": ["Looker", "SQL & BigQuery"]}, "screen": {"score": 82},
            "flags": [], "folder": str(tmp_path)} | kw


def test_every_message_is_valid_telegram_html(tmp_path):
    r = res(tmp_path, flags=["number '30' is not in the profile"], tier=2)
    for text in (notify.card(JOB, FIT, r), notify.outreach_html(PACK), notify.prep_html(BRIEF, PACK, ["A & B"])):
        assert telegram_html_errors(text) == []


def test_card_is_short_and_has_what_matters(tmp_path):
    text = notify.card(JOB, FIT, res(tmp_path))
    lines = text.splitlines()
    assert len(lines) <= 8 and len(text) < 900
    assert "(H/F)" not in lines[0] and "81/100" in lines[0]
    assert "CDI" in lines[1] and "posted" in lines[1]
    assert 'href="https://example.com/job?a=1&amp;b=2"' in text  # falls back to the posting when no apply link
    assert "follow" not in text.lower()


def test_outreach_has_no_follow_up_yet():
    assert "Bonjour, je me permets de revenir" not in notify.outreach_html(PACK)


def test_deliver_sends_three_bubbles_per_job(telegram, cand, tmp_path):
    banner = tmp_path / "banner.png"
    banner.write_bytes(b"\x89PNG fake")
    assert notify.deliver(cand, JOB, FIT, res(tmp_path, banner=banner), "abc") is True
    assert [m for m, *_ in telegram.calls] == ["sendPhoto", "sendMediaGroup", "sendMessage"]
    photo = telegram.calls[0][1]
    assert telegram_html_errors(photo["caption"]) == [] and len(photo["caption"]) <= 1024
    assert json.loads(photo["reply_markup"])["inline_keyboard"][0][0]["callback_data"] == "a:abc"
    media = json.loads(telegram.calls[1][1]["media"])
    assert len(media) == 2 and "caption" not in media[-1]
    last = telegram.texts()[-1]
    assert "LinkedIn note" in last and "Interview prep" in last and telegram_html_errors(last) == []


def test_portal_jobs_get_the_word_cv_instead_of_the_pdf(telegram, cand, tmp_path):
    docx = tmp_path / "Alex-Moreau-CV-X.docx"
    docx.write_bytes(b"PK fake docx")
    assert notify.deliver(cand, JOB, FIT, res(tmp_path, docx=str(docx), portal="Workday"), "abc") is True
    files = next(f for m, _, f in telegram.calls if m == "sendMediaGroup")
    assert files == ["Alex-Moreau-CV-X.docx", "Alex-Moreau-Lettre-X.pdf"]  # one CV: the Word one
    card = telegram.texts()[0]
    assert "Workday reads Word best" in card and telegram_html_errors(card) == []


def test_without_a_header_picture_the_card_goes_as_text(telegram, cand, tmp_path):
    telegram.script["sendPhoto"] = [{"ok": False, "error_code": 400, "description": "Bad Request: wrong file"}]
    banner = tmp_path / "banner.png"
    banner.write_bytes(b"\x89PNG fake")
    assert notify.deliver(cand, JOB, FIT, res(tmp_path, banner=banner), "abc") is True
    assert [m for m, *_ in telegram.calls] == ["sendPhoto", "sendMessage", "sendMediaGroup", "sendMessage"]
    assert notify.deliver(cand, JOB, FIT, res(tmp_path), "abc") is True  # no picture at all


def test_long_prep_never_breaks_the_message(tmp_path):
    brief = BRIEF | {"recent_news": ["R&D " * 400], "ideas": ["& < >" * 300]}
    out = notify.outreach_html(PACK)
    prep = notify.prep_html(brief, PACK, ["x"] * 50, 3900 - len(out))
    assert telegram_html_errors(out + "\n\n" + prep) == []


def test_too_many_requests_is_retried(telegram, cand):
    telegram.script["sendMessage"] = [{"ok": False, "error_code": 429, "description": "Too Many Requests",
                                       "parameters": {"retry_after": 3}}]
    assert notify.Telegram(cand).send("hello").get("ok")
    assert len(telegram.calls) == 2


def test_parse_error_falls_back_to_plain_text(telegram, cand):
    telegram.script["sendMessage"] = [{"ok": False, "error_code": 400, "description": "Bad Request: can't parse entities"}]
    assert notify.Telegram(cand).send("<b>broken").get("ok")
    assert "parse_mode" not in telegram.calls[1][1] and telegram.calls[1][1]["text"] == "broken"


def test_files_go_one_by_one_when_the_group_fails(telegram, cand, tmp_path):
    telegram.script["sendMediaGroup"] = [{"ok": False, "error_code": 400, "description": "Bad Request"}]
    assert notify.deliver(cand, JOB, FIT, res(tmp_path), "abc") is True
    assert [m for m, *_ in telegram.calls].count("sendDocument") == 2


def test_failed_card_is_reported_and_delivered_next_run(telegram, cand, tmp_path):
    telegram.script["sendMessage"] = [{"ok": False, "error_code": 502, "description": "Bad Gateway"}] * 4
    r = res(tmp_path)
    assert notify.deliver(cand, JOB, FIT, r, "abc") is False
    store = Store(cand)
    store.save(JOB, "undelivered", 81, 1, {"fit": FIT, "lang": "fr", "ats": r["ats"], "screen": r["screen"],
                                         "flags": [], "folder": str(tmp_path), "pdf": str(r["pdf"]),
                                         "letter": str(r["letter_pdf"]), "pack": PACK, "brief": BRIEF})
    telegram.calls.clear()
    pipeline.redeliver(cand, store)  # Telegram is back
    assert store.by_cb(short_id(JOB["id"]))["status"] == "sent"
    assert [m for m, *_ in telegram.calls][:2] == ["sendMessage", "sendMediaGroup"]


def test_alerts_go_to_the_admin_chat_once(telegram, cand, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "7")
    notify.alert(cand, "Pack failed: X & Y")
    notify.alert(cand, "Pack failed: X & Y")
    sends = [d for m, d, _ in telegram.calls if m == "sendMessage"]
    assert len(sends) == 1 and sends[0]["chat_id"] == "7" and telegram_html_errors(sends[0]["text"]) == []


def test_follow_up_arrives_only_when_due(telegram, cand):
    store = Store(cand)
    store.save(JOB, "sent", 81, 1, {"follow_up": PACK["follow_up"]})
    store.set_status(JOB["id"], "applied")
    pipeline.remind(cand, store)
    assert telegram.texts() == []  # applied today: nothing yet
    store.db.execute("update jobs set applied_at='2026-01-01T00:00:00+00:00'")
    pipeline.remind(cand, store)
    pipeline.remind(cand, store)
    texts = telegram.texts()
    assert len(texts) == 1 and "Follow-up time" in texts[0] and telegram_html_errors(texts[0]) == []
    assert "(H/F)" not in texts[0]


@pytest.mark.parametrize("command", ["/start", "/status", "hello"])
def test_bot_replies_are_valid(telegram, cand, command):
    import queue

    from hunter import bot

    update = {"update_id": 1, "message": {"chat": {"id": 42}, "text": command}}
    bot.handle(cand, notify.Telegram(cand), Store(cand), update, queue.Queue())
    assert telegram.texts() and all(telegram_html_errors(t) == [] for t in telegram.texts())


def test_bot_ignores_other_chats_and_queues_links(telegram, cand):
    import queue

    from hunter import bot

    links = queue.Queue()
    tg, store = notify.Telegram(cand), Store(cand)
    bot.handle(cand, tg, store, {"update_id": 1, "message": {"chat": {"id": 666}, "text": "/status"}}, links)
    assert telegram.calls == []
    bot.handle(cand, tg, store, {"update_id": 2, "message": {"chat": {"id": 42},
                                                             "text": "look https://jobs.lever.co/x/123"}}, links)
    assert links.get_nowait() == "https://jobs.lever.co/x/123"


def test_outcome_buttons_follow_the_job(telegram, cand):
    import queue

    from hunter import bot

    store, tg = Store(cand), notify.Telegram(cand)
    store.save(JOB, "sent", 81, 1, {})
    cb = short_id(JOB["id"])

    def press(action):
        bot.handle(cand, tg, store, {"update_id": 1, "callback_query": {
            "id": "q", "data": f"{action}:{cb}", "message": {"chat": {"id": 42}, "message_id": 9}}}, queue.Queue())
        markup = json.loads(telegram.calls[-1][1]["reply_markup"])["inline_keyboard"]
        return store.by_cb(cb), [b["text"] for row in markup for b in row]

    row, labels = press("a")
    assert row["status"] == "applied" and row["applied_at"] and "🎤 Got an interview" in labels
    row, labels = press("i")
    assert row["status"] == "interview" and row["interview_at"] and "🎉 Got an offer" in labels
    row, labels = press("r")
    assert row["status"] == "rejected" and row["interview_at"]  # the interview still counts
    row, _ = press("u")
    assert row["status"] == "interview"
    row, _ = press("u")
    assert row["status"] == "applied" and not row["interview_at"]
    row, labels = press("u")
    assert row["status"] == "sent" and not row["applied_at"] and labels == ["✅ I applied", "🙅 Not for me"]


def test_weekly_summary_once_on_monday(telegram, cand):
    from datetime import date, datetime, timedelta

    today = date.today()
    monday = datetime.combine(today + timedelta(days=(7 - today.weekday()) % 7), datetime.min.time()).replace(hour=9)
    store = Store(cand)
    for i, (status, site) in enumerate([("sent", "linkedin"), ("applied", "career page (ashby)"),
                                        ("interview", "indeed"), ("rejected", "career page")]):
        job = JOB | {"id": f"j{i}", "title": f"Job {i} (H/F)", "site": site, "company": f"Co {i} & Fils"}
        store.save(job, "sent", 70 + i, 1, {"sent_on": today.isoformat()})
        for step in {"sent": [], "applied": ["applied"], "interview": ["applied", "interview"],
                     "rejected": ["applied", "rejected"]}[status]:
            store.set_status(job["id"], step)
    pipeline.weekly_summary(cand, store, monday - timedelta(days=1))  # Sunday: nothing
    pipeline.weekly_summary(cand, store, monday)
    pipeline.weekly_summary(cand, store, monday)  # once a week
    texts = telegram.texts()
    assert len(texts) == 1 and telegram_html_errors(texts[0]) == []
    assert "Jobs sent: 4 (company sites 2" in texts[0] and "Interviews: 1" in texts[0]
    assert "Best: <b>Job 0 · Co 0 &amp; Fils</b>" in texts[0] and "1 interview from 3 applications (33%)" in texts[0]


def test_buttons_update_the_job(telegram, cand):
    import queue

    from hunter import bot

    store = Store(cand)
    store.save(JOB, "sent", 81, 1, {})
    cb = short_id(JOB["id"])
    press = {"update_id": 3, "callback_query": {"id": "q", "data": f"a:{cb}",
                                                "message": {"chat": {"id": 42}, "message_id": 9}}}
    bot.handle(cand, notify.Telegram(cand), store, press, queue.Queue())
    assert store.by_cb(cb)["status"] == "applied"
    stale = {"update_id": 4, "callback_query": {"id": "q2", "data": "a:unknown",
                                                "message": {"chat": {"id": 42}, "message_id": 9}}}
    bot.handle(cand, notify.Telegram(cand), store, stale, queue.Queue())
    assert telegram.calls[-1][1]["text"] == "This job is no longer tracked."


def test_the_bot_token_never_reaches_the_log(telegram, cand, monkeypatch, caplog):
    def down(url, **kw):
        raise notify.requests.ConnectionError(f"Max retries exceeded with url: {url}")

    monkeypatch.setattr(notify.requests, "post", down)
    notify.Telegram(cand).send("hello")
    assert "123:test" not in caplog.text and "<token>" in caplog.text


def test_alerts_keep_only_the_first_line_of_an_error():
    e = RuntimeError("BrowserType.launch: Executable doesn't exist at C:/x.exe\n╔════╗\n║ Looks like Playwright was updated ║")
    assert notify.first_line(e) == "BrowserType.launch: Executable doesn't exist at C:/x.exe"


def test_usage_heads_up_goes_to_the_admin_chat(telegram, cand, monkeypatch):
    import hunter.llm as llm

    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "7")
    monkeypatch.setattr(llm, "usage_by_day", lambda days=7: [{"day": "2026-10-30", "calls": 999}])
    cand.config["claude"]["daily_call_warning"] = 400
    pipeline.watch_usage(cand, Store(cand))
    sends = [d for m, d, _ in telegram.calls if m == "sendMessage"]
    assert len(sends) == 1 and sends[0]["chat_id"] == "7"

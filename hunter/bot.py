"""Telegram side: setup, the Applied / Not for me buttons, and "send me any job link".
Only the candidate's own chat is listened to."""
import html
import json
import logging
import queue
import re
import threading
import time

from .candidate import ROOT
from .notify import Telegram, buttons
from .store import Store

log = logging.getLogger(__name__)
URL = re.compile(r"https?://\S+")
HELP = ("Hi! I watch job boards and company career pages and send you a tailored CV, cover letter and "
        "outreach messages for every good match.\n\n"
        "• Tap <b>I applied</b> under a job to track it: a week later I send you the follow-up to copy.\n"
        "• Then tap <b>Got an interview</b>, <b>Got an offer</b> or <b>Rejected</b>: it shows what works.\n"
        "• Send me <b>any job link</b> and I build the pack for it.\n"
        "• /status shows the numbers; a short summary comes every Monday.")
STATUS = {"a": "applied", "x": "not_for_me", "f": "followed_up", "i": "interview", "r": "rejected", "o": "offer"}
UNDO = {"applied": "sent", "not_for_me": "sent", "followed_up": "sent", "interview": "applied",
        "rejected": "applied", "offer": "interview"}  # one step back
REPLY = {"applied": "Tracked ✅ A week from now you get the follow-up to send.", "not_for_me": "Got it, skipped.",
         "followed_up": "Nice, follow-up logged.", "interview": "🎤 Well done! The interview prep is under the job.",
         "rejected": "Logged. On to the next one.", "offer": "🎉 Congratulations!"}


def set_env(key: str, value: str):
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [l for l in lines if not l.startswith(f"{key}=")] + [f"{key}={value}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def setup(cand, wait_s: int = 300):
    """Find the chat that wrote to the bot, save its id for this candidate, send a test message."""
    tg = Telegram(cand)
    if not tg.token:
        print("Add TELEGRAM_BOT_TOKEN=... to .env first (create the bot with @BotFather in Telegram).")
        return
    me = tg.call("getMe").get("result") or {}
    if not me:
        print("The bot token was rejected by Telegram. Check TELEGRAM_BOT_TOKEN in .env.")
        return
    print(f"Open https://t.me/{me['username']} on the phone that should receive the jobs and press Start.")
    print(f"Waiting up to {wait_s // 60} minutes...")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        updates = tg.call("getUpdates", timeout=40, data={"timeout": 30}).get("result", [])
        chats = [u["message"]["chat"] for u in updates if "message" in u]
        if chats:
            chat = chats[-1]
            key = f"TELEGRAM_CHAT_ID_{cand.name.upper()}"
            if tg.chat and tg.chat != str(chat["id"]) and not cand.env("TELEGRAM_ADMIN_CHAT_ID"):
                # Handing over (your test chat -> the candidate's phone): errors keep going to the previous chat.
                set_env("TELEGRAM_ADMIN_CHAT_ID", tg.chat)
                print("The previous chat now gets error alerts (TELEGRAM_ADMIN_CHAT_ID in .env).")
            set_env(key, str(chat["id"]))
            tg.chat = str(chat["id"])
            tg.send(f"✅ Connected. Job packs for <b>{html.escape(cand.full_name)}</b> will arrive here.\n\n{HELP}")
            tg.call("getUpdates", data={"offset": updates[-1]["update_id"] + 1})  # don't replay /start later
            print(f"Connected to {chat.get('first_name') or chat.get('title')} (saved {key} in .env).")
            return
    print("No message received. Press Start in the bot chat, then run this again.")


def listen(cand, links: "queue.Queue[str]", stop: threading.Event):
    """Long-poll Telegram: handle buttons right away, queue job links for the worker."""
    tg, store = Telegram(cand), Store(cand)
    offset = int(store.get("tg_offset", "0") or 0)
    while not stop.is_set():
        data = tg.call("getUpdates", timeout=70, data={
            "offset": offset, "timeout": 50, "allowed_updates": json.dumps(["message", "callback_query"])})
        if not data.get("ok"):  # network down, or 409: another copy of the bot is already listening
            time.sleep(30 if data.get("error_code") == 409 else 10)
        for u in data.get("result", []):
            offset = u["update_id"] + 1
            store.put("tg_offset", str(offset))
            try:
                handle(cand, tg, store, u, links)
            except Exception as e:
                log.warning("telegram update failed: %s", e)


def handle(cand, tg: Telegram, store: Store, u: dict, links: "queue.Queue[str]"):
    if "callback_query" in u:
        q = u["callback_query"]
        msg = q.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != tg.chat:
            return
        action, _, cb = (q.get("data") or "").partition(":")
        row = store.by_cb(cb) if cb else None
        if row and (action in STATUS or action == "u"):
            status = UNDO.get(row["status"], "sent") if action == "u" else STATUS[action]
            if action == "u" and row["status"] == "rejected" and row["interview_at"]:
                status = "interview"  # rejected after an interview: undo goes back to the interview
            store.set_status(row["id"], status)
            tg.call("answerCallbackQuery", data={"callback_query_id": q["id"], "text": REPLY.get(status, "Undone.")})
            tg.call("editMessageReplyMarkup", data={"chat_id": tg.chat, "message_id": msg["message_id"],
                                                    "reply_markup": json.dumps(buttons(cb, status))})
        else:  # a button from before a reset, or the inert "Applied" label
            tg.call("answerCallbackQuery", data={"callback_query_id": q["id"],
                                                 "text": "" if action == "noop" else "This job is no longer tracked."})
        return
    msg = u.get("message") or {}
    if str((msg.get("chat") or {}).get("id")) != tg.chat:
        return
    text = msg.get("text") or ""
    if text.startswith("/start") or text.startswith("/help"):
        tg.send(HELP)
    elif text.startswith("/status"):
        from .llm import usage_by_day
        c = store.counts()
        today = (usage_by_day(1) or [{"calls": 0}])[0]
        applied = sum(c.get(s, 0) for s in ("applied", "followed_up", "interview", "rejected", "offer"))
        total = applied + sum(c.get(s, 0) for s in ("sent", "not_for_me", "undelivered"))
        tg.send(f"📊 <b>Status</b>\n• Jobs sent to you: {total}\n• Applied: {applied}\n"
                f"• Interviews: {c.get('interview', 0) + c.get('offer', 0)} · Offers: {c.get('offer', 0)} · "
                f"Rejected: {c.get('rejected', 0)}\n• Not for me: {c.get('not_for_me', 0)}\n"
                f"• Good matches waiting: {c.get('queued', 0)}\n"
                f"• Career pages watched: {len(store.companies())}\n• Claude calls today: {today['calls']}")
    elif URL.search(text):
        url = URL.search(text).group(0)
        links.put(url)
        tg.send("On it: building the pack for this job. It takes a few minutes.")
    else:
        tg.send("Send me a job link, or /status.")


def worker(cand, links: "queue.Queue[str]", stop: threading.Event):
    from .pipeline import apply_to

    tg = Telegram(cand)
    while not stop.is_set():
        try:
            url = links.get(timeout=5)
        except queue.Empty:
            continue
        try:
            note = apply_to(cand, url)
        except Exception as e:
            log.exception("link pack failed")
            note = f"Sorry, that one failed: {e}"
        if note.startswith("Could not") or note.startswith("Sorry"):
            tg.send(html.escape(note))

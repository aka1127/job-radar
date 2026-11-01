"""Telegram side: setup, the Applied / Not for me buttons, and "send me any job link".
Only the candidate's own chat is listened to. Every sentence comes from brand.text (config.yaml `texts:`)."""
import html
import json
import logging
import queue
import re
import sys
import threading
import time

from .brand import text
from .candidate import HOME
from .notify import Telegram, buttons
from .store import Store

log = logging.getLogger(__name__)
URL = re.compile(r"https?://\S+")
STATUS = {"a": "applied", "x": "not_for_me", "f": "followed_up", "i": "interview", "r": "rejected", "o": "offer"}
UNDO = {"applied": "sent", "not_for_me": "sent", "followed_up": "sent", "interview": "applied",
        "rejected": "applied", "offer": "interview"}  # one step back


def set_env(key: str, value: str):
    path = HOME / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [l for l in lines if not l.startswith(f"{key}=")] + [f"{key}={value}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _confirm(chat: dict) -> bool:
    """The bot's username is public: whoever wrote to it last must be the person we mean. In a terminal, ask."""
    who = chat.get("first_name") or chat.get("title") or chat.get("username") or "?"
    handle = f"@{chat['username']}" if chat.get("username") else "no username"
    if not sys.stdin.isatty():
        print(f"Connecting {who} ({handle}, chat id {chat['id']}).")
        return True
    try:
        answer = input(f"Connect {who} ({handle}, chat id {chat['id']})? [Y/n] ").strip().lower()
    except EOFError:
        return True
    return answer in ("", "y", "yes", "o", "oui", "j", "ja", "s", "si", "sí")


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
            tg.call("getUpdates", data={"offset": updates[-1]["update_id"] + 1})  # don't replay /start later
            if not _confirm(chat):
                print("Not connected. Press Start from the right phone, then run this again.")
                return
            key = f"TELEGRAM_CHAT_ID_{cand.name.upper()}"
            if tg.chat and tg.chat != str(chat["id"]) and not cand.env("TELEGRAM_ADMIN_CHAT_ID"):
                # Handing over (your test chat -> the candidate's phone): errors keep going to the previous chat.
                set_env("TELEGRAM_ADMIN_CHAT_ID", tg.chat)
                print("The previous chat now gets error alerts (TELEGRAM_ADMIN_CHAT_ID in .env).")
            set_env(key, str(chat["id"]))
            tg.chat = str(chat["id"])
            tg.send(f"{text('connected', name=html.escape(cand.full_name))}\n\n{text('help')}")
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
            reply = text(f"reply_{status}") if status != "sent" else text("reply_undone")
            tg.call("answerCallbackQuery", data={"callback_query_id": q["id"], "text": reply})
            tg.call("editMessageReplyMarkup", data={"chat_id": tg.chat, "message_id": msg["message_id"],
                                                    "reply_markup": json.dumps(buttons(cb, status))})
        else:  # a button from before a reset, or the inert "Applied" label
            tg.call("answerCallbackQuery", data={"callback_query_id": q["id"],
                                                 "text": "" if action == "noop" else text("not_tracked")})
        return
    msg = u.get("message") or {}
    if str((msg.get("chat") or {}).get("id")) != tg.chat:
        return
    body = msg.get("text") or ""
    if body.startswith("/start") or body.startswith("/help"):
        tg.send(text("help"))
    elif body.startswith("/status"):
        from .llm import usage_by_day
        c = store.counts()
        today = (usage_by_day(1) or [{"calls": 0}])[0]
        applied = sum(c.get(s, 0) for s in ("applied", "followed_up", "interview", "rejected", "offer"))
        total = applied + sum(c.get(s, 0) for s in ("sent", "not_for_me", "undelivered"))
        tg.send(text("status", total=total, applied=applied, interviews=c.get("interview", 0) + c.get("offer", 0),
                     offers=c.get("offer", 0), rejected=c.get("rejected", 0), not_for_me=c.get("not_for_me", 0),
                     queued=c.get("queued", 0), companies=len(store.companies()), calls=today["calls"]))
    elif URL.search(body):
        links.put(URL.search(body).group(0))
        tg.send(text("on_it"))
    else:
        tg.send(text("send_link"))


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
            note = text("link_failed", error=e)
        if note.startswith("Could not") or note.startswith("Sorry") or note == text("link_unreadable"):
            tg.send(html.escape(note))

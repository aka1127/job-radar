"""Deliver application packs to Telegram (with Applied / Not for me buttons) and/or email."""
import html
import json
import logging
import os
import re
import smtplib
import time
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote_plus

import requests

from . import targets
from .ats import role_title
from .brand import text
from .candidate import HOME
from .text import display_title

log = logging.getLogger(__name__)
SENT_LOG = HOME / "data" / "telegram.jsonl"


def people_search_url(company: str, title: str) -> str:
    return "https://www.linkedin.com/search/results/people/?keywords=" + quote_plus(f"{title} {company}")


def brief_text(brief: dict | None) -> str:
    if not brief:
        return ""
    parts = [brief.get("what_they_do", "")]
    for label, key in (("brief_news", "recent_news"), ("brief_snapshot", "marketing_snapshot"),
                       ("brief_ideas", "ideas"), ("brief_questions", "questions")):
        if brief.get(key):
            parts.append(f"{text(label)}:\n" + "\n".join(f"- {x}" for x in brief[key]))
    return "\n\n".join(p for p in parts if p)


def outreach_text(pack: dict, follow_up: bool = True) -> str:
    later = f"\n\n{text('txt_followup')}\n{pack['follow_up']}" if follow_up else ""
    return (f"{text('txt_note')}\n{pack['linkedin_note']}\n\n{text('txt_message')}\n{pack['hiring_manager_message']}"
            f"{later}\n\n{text('txt_who')}: {', '.join(pack['hiring_manager_titles'])}"
            f"\n\n{text('txt_angles')}\n" + "\n".join(f"- {a}" for a in pack["interview_angles"]))


LABEL = {"applied": "label_applied", "followed_up": "label_applied", "not_for_me": "label_skipped",
         "interview": "label_interview", "rejected": "label_rejected", "offer": "label_offer"}


def buttons(cb: str, status: str = "sent") -> dict:
    """The buttons under a job follow it through: applied, then interview, then offer (or rejected)."""
    def b(key, action):
        return {"text": text(key), "callback_data": f"{action}:{cb}" if action != "noop" else "noop"}

    if status not in LABEL:
        return {"inline_keyboard": [[b("btn_applied", "a"), b("btn_not_for_me", "x")]]}
    rows = [[b(LABEL[status], "noop"), b("btn_undo", "u")]]
    if status in ("applied", "followed_up"):
        rows.append([b("btn_interview", "i"), b("btn_rejected", "r")])
    elif status == "interview":
        rows.append([b("btn_offer", "o"), b("btn_rejected", "r")])
    return {"inline_keyboard": rows}


class Telegram:
    def __init__(self, cand):
        self.token = cand.env("TELEGRAM_BOT_TOKEN")  # one bot per candidate, or a shared one
        self.chat = cand.env("TELEGRAM_CHAT_ID")

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat)

    def call(self, method: str, timeout: int = 60, **kw) -> dict:
        data = self._call(method, timeout, **kw)
        if method.startswith(("send", "edit")):  # what went out and whether Telegram took it: data/telegram.jsonl
            sent = kw.get("data") or {}
            row = {"at": datetime.now().isoformat(timespec="seconds"), "method": method, "ok": bool(data.get("ok")),
                   "error": data.get("description", "") if not data.get("ok") else "",
                   "chat": str(sent.get("chat_id", "")),
                   "text": str(sent.get("text") or sent.get("caption") or "")[:4096],
                   "files": [f[0] for f in (kw.get("files") or {}).values()]}
            try:
                with open(SENT_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return data

    def _call(self, method: str, timeout: int = 60, **kw) -> dict:
        """One Bot API call. Network errors, "Too Many Requests" and Telegram-side errors are retried."""
        for attempt in range(4):
            try:
                r = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", timeout=timeout, **kw)
                data = r.json()
            except (requests.RequestException, ValueError) as e:
                # The request URL carries the bot token: never let it reach a log file.
                log.warning("telegram %s failed (attempt %d): %s", method, attempt + 1,
                            str(e).replace(self.token, "<token>") if self.token else e)
                data, wait = {}, 5 * (attempt + 1)
            else:
                if data.get("ok"):
                    return data
                code = data.get("error_code") or 0
                if code != 429 and code < 500:  # a bad request will not get better by retrying
                    log.warning("telegram %s: %s", method, data.get("description"))
                    return data
                wait = (data.get("parameters") or {}).get("retry_after") or 5 * (attempt + 1)
                log.info("telegram %s: %s, retrying in %ss", method, data.get("description"), wait)
            if method == "getUpdates" or attempt == 3:
                return data
            time.sleep(min(wait, 60))
        return data

    def send(self, text: str, markup: dict | None = None, chat: str | None = None) -> dict:
        data = {"chat_id": chat or self.chat, "text": text, "parse_mode": "HTML",
                "link_preview_options": json.dumps({"is_disabled": True})}
        if markup:
            data["reply_markup"] = json.dumps(markup)
        if len(text) > 4096:  # Telegram's limit: cutting HTML would break it, so fall back to plain text
            data.pop("parse_mode")
            data["text"] = html.unescape(re.sub(r"<[^>]+>", "", text))[:4096]
        sent = self.call("sendMessage", data=data)
        if not sent.get("ok") and "parse" in str(sent.get("description", "")) and "parse_mode" in data:
            data.pop("parse_mode")
            data["text"] = html.unescape(re.sub(r"<[^>]+>", "", text))[:4096]
            sent = self.call("sendMessage", data=data)
        return sent

    def photo(self, path: Path, caption: str, markup: dict | None = None) -> dict:
        data = {"chat_id": self.chat, "caption": caption, "parse_mode": "HTML"}
        if markup:
            data["reply_markup"] = json.dumps(markup)
        return self.call("sendPhoto", data=data, files={"photo": (path.name, path.read_bytes())})

    def documents(self, paths: list[Path], caption: str = "") -> bool:
        """The PDFs as one group; one by one if the group fails. False when a file could not be sent."""
        media, files = [], {}
        for i, p in enumerate(paths):
            media.append({"type": "document", "media": f"attach://f{i}"})
            files[f"f{i}"] = (p.name, p.read_bytes())
        if caption:
            media[-1]["caption"] = caption[:1000]
        if self.call("sendMediaGroup", data={"chat_id": self.chat, "media": json.dumps(media)}, files=files).get("ok"):
            return True
        return all([self.call("sendDocument", data={"chat_id": self.chat},
                              files={"document": (p.name, p.read_bytes())}).get("ok") for p in paths])


class Email:
    def __init__(self, cand):
        self.host, self.user = os.getenv("SMTP_HOST", ""), os.getenv("SMTP_USER", "")
        self.password, self.to = os.getenv("SMTP_PASSWORD", ""), cand.env("EMAIL_TO")
        self.port = int(os.getenv("SMTP_PORT") or 587)

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.user and self.password and self.to)

    def send(self, subject: str, body: str, attachments: list[Path]):
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, self.user, self.to
        msg.set_content(body)
        for p in attachments:
            sub = "pdf" if p.suffix == ".pdf" else "vnd.openxmlformats-officedocument.wordprocessingml.document"
            msg.add_attachment(p.read_bytes(), maintype="application", subtype=sub, filename=p.name)
        with smtplib.SMTP(self.host, self.port) as s:
            s.starttls()
            s.login(self.user, self.password)
            s.send_message(msg)


def short_place(location: str) -> str:
    return (location or "").split(",")[0].split(" / ")[0].strip() or "?"


def age(posted: str) -> str:
    try:
        days = (date.today() - date.fromisoformat((posted or "")[:10])).days
    except ValueError:
        return ""
    return text("posted_today") if days <= 0 else text("posted_yesterday") if days == 1 else text("posted_days", days=days)


def card(job: dict, fit: dict, res: dict, cfg: dict | None = None) -> str:
    """The job at a glance: what, where, how good, what to do. Short on purpose."""
    e, cfg = html.escape, cfg or {}
    contract = targets.contract_label(fit.get("contract"), cfg)
    where = short_place(job["location"]) + (text("outside", home=targets.home_label(cfg)) if res["tier"] == 2 else "")
    meta = " · ".join(x for x in (where, contract, age(job.get("posted"))) if x)
    p = targets.priority(cfg)  # the candidate's priority sector, marked on top
    lines = ([text("priority_head", emoji=p.get("emoji") or "⭐", label=e(p.get("label") or text("priority_label")))]
             if targets.is_priority(fit, cfg) else [])
    lines += [f"<b>{fit['score']}/100 · {e(display_title(role_title(job['title'], job['company'])))}</b>",
             f"🏢 <b>{e(job['company'] or '?')}</b> · {e(meta)}"]
    if fit["why_fit"]:  # items can hold commas themselves ("CRM: HubSpot, ActiveCampaign")
        lines.append(f"• ✅ {e(' · '.join(fit['why_fit'][:3]))}")
    if fit["gaps"]:
        lines.append(f"• ⚠️ {e(' · '.join(fit['gaps'][:2]))}")
    lines.append(text("cv_scores", lang=res["lang"].upper(), ats=res["ats"]["score"], screener=res["screen"]["score"]))
    if res.get("docx"):
        lines.append(text("word_cv", portal=e(res.get("portal") or text("this_portal"))))
    if job.get("summary_only"):
        lines.append(text("summary_only"))
    if res["flags"]:
        lines.append(text("check_before", flags=e("; ".join(res["flags"][:3]))))
    hm = people_search_url(job["company"], (res["pack"]["hiring_manager_titles"] or [""])[0])
    lines.append(f'👉 <a href="{e(job["apply_url"] or job["url"])}">{text("apply")}</a> · '
                 f'<a href="{e(hm)}">{text("find_manager")}</a>')
    return "\n".join(lines)


def outreach_html(pack: dict) -> str:
    """The two messages to copy now. The follow-up arrives later, only when it is due."""
    e = html.escape
    return (f"{text('note')}\n<pre>{e(pack['linkedin_note'])}</pre>\n"
            f"{text('message')}\n<pre>{e(pack['hiring_manager_message'])}</pre>\n"
            f"{text('who', titles=e(', '.join(pack['hiring_manager_titles'][:3])))}")


def prep_html(brief: dict | None, pack: dict, missing: list[str], room: int = 3500) -> str:
    """Interview prep, collapsed: opened only when an interview comes. room: characters left in the message."""
    items = []
    if brief:
        if brief.get("what_they_do"):
            items.append(f"• {brief['what_they_do']}")
        items += [f"• {text('prep_news')}: {n}" for n in (brief.get("recent_news") or [])[:2]]
        items += [f"• {text('prep_idea')}: {i}" for i in (brief.get("ideas") or [])[:2]]
        items += [f"• {text('prep_ask')}: {q}" for q in (brief.get("questions") or [])[:2]]
    items += [f"• {text('prep_say')}: {a}" for a in pack.get("interview_angles", [])[:3]]
    if missing:
        items.append(f"• {text('prep_missing')}: " + ", ".join(missing[:8]))
    if not items:
        return ""
    body = html.escape("\n".join(items))
    if len(body) > room - 60:  # cut on a line, never inside an &amp; entity
        body = body[:max(0, room - 60)].rsplit("\n", 1)[0]
    return f"{text('prep')}\n<blockquote expandable>" + body + "</blockquote>" if body.strip() else ""


_alerted: dict[str, float] = {}


def first_line(error: Exception) -> str:
    """Errors can carry pages of text (Playwright draws boxes): an alert keeps the first line."""
    return (str(error).strip().splitlines() or [""])[0][:200]


def alert(cand, text: str):
    """Problems go to the admin chat (whoever runs the engine) when one is set, so the candidate only ever sees jobs.
    The same alert is sent at most once every 6 hours."""
    tg = Telegram(cand)
    admin = cand.env("TELEGRAM_ADMIN_CHAT_ID")
    if not tg.token or not (admin or tg.chat) or time.time() - _alerted.get(text, 0) < 6 * 3600:
        return
    _alerted[text] = time.time()
    tg.send(globals()["text"]("alert", text=html.escape(text)[:3500]), chat=admin or None)


def deliver(cand, job: dict, fit: dict, res: dict, cb: str) -> bool:
    """Send one pack. False when Telegram did not take the card or the PDFs: the job is then retried."""
    tg, em = Telegram(cand), Email(cand)
    files = [Path(res["docx"]) if res.get("docx") else res["pdf"], res["letter_pdf"]]  # one CV, Word for portals
    ok = True
    if tg.enabled:
        # Three bubbles per job: the branded header with the card and buttons, the PDFs, the messages to copy.
        head, banner, sent = card(job, fit, res, cand.config), res.get("banner"), {}
        if banner and Path(banner).exists() and len(head) <= 1000:  # captions stop at 1024 characters
            sent = tg.photo(Path(banner), head, buttons(cb))
        if not sent.get("ok"):  # no picture, or Telegram refused it: the card alone still works
            sent = tg.send(head, buttons(cb))
        ok = bool(sent.get("ok")) and tg.documents(files)
        if ok:
            outreach = outreach_html(res["pack"])
            prep = prep_html(res["brief"], res["pack"], res["ats"]["missing"], 3900 - len(outreach))
            tg.send(outreach + (f"\n\n{prep}" if prep else ""))
    if em.enabled:
        plain = html.unescape(re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"\2: \1", card(job, fit, res, cand.config)))
        body = (re.sub(r"<[^>]+>", "", plain) + "\n\n" + outreach_text(res["pack"], follow_up=False)
                + f"\n\n{text('txt_letter')}\n\n" + res["pack"]["cover_letter"] + f"\n\n{text('txt_brief')}\n\n"
                + brief_text(res["brief"]))
        try:
            em.send(text("email_subject", score=fit["score"], title=display_title(job["title"]), company=job["company"]),
                    body, files)
        except Exception as e:
            log.warning("email failed: %s", e)
    if not (tg.enabled or em.enabled):
        print(f"\n{fit['score']}/100 {job['title']} | {job['company']} -> {res['folder']}", flush=True)
    return ok

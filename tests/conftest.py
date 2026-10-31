"""Shared test setup. Everything runs offline: Telegram, job boards and Claude are faked, and the database
and output folders live in a temporary directory, never in data/ or output/."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from hunter.candidate import Candidate

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cand(tmp_path, monkeypatch):
    import hunter.archive

    monkeypatch.setattr(hunter.archive, "DB", tmp_path / "jobs.db")  # never the real national archive
    c = Candidate("example")  # fictional person: the tests never touch real data
    c.db_path = tmp_path / "test.db"
    c.out = tmp_path / "output"
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_CHAT_ID_EXAMPLE", "TELEGRAM_ADMIN_CHAT_ID",
                "TELEGRAM_ADMIN_CHAT_ID_EXAMPLE", "SMTP_HOST", "EMAIL_TO", "EMAIL_TO_EXAMPLE", "ALERTS_IMAP_USER",
                "ALERTS_IMAP_USER_EXAMPLE", "ALERTS_IMAP_PASSWORD", "ALERTS_IMAP_PASSWORD_EXAMPLE"):
        monkeypatch.delenv(key, raising=False)
    return c


@pytest.fixture
def cv_en():
    return json.loads((FIXTURES / "cv_en.json").read_text(encoding="utf-8"))


@pytest.fixture
def cv_fr():
    return json.loads((FIXTURES / "cv_fr.json").read_text(encoding="utf-8"))


class FakeTelegram:
    """Stands in for api.telegram.org: records every call and answers from a script (default: ok)."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.script: dict[str, list[dict]] = {}

    def post(self, url, timeout=None, data=None, files=None, **kw):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, dict(data or {}), [f[0] for f in (files or {}).values()]))
        answers = self.script.get(method)
        body = answers.pop(0) if answers else {"ok": True, "result": {"message_id": len(self.calls)}}

        class Response:
            def json(self):
                return body
        return Response()

    def texts(self) -> list[str]:
        return [d["text"] for m, d, _ in self.calls if m == "sendMessage"]


@pytest.fixture
def telegram(monkeypatch, cand, tmp_path):  # after cand, which clears the real Telegram settings
    import hunter.notify as notify

    fake = FakeTelegram()
    monkeypatch.setattr(notify, "SENT_LOG", tmp_path / "telegram.jsonl")
    monkeypatch.setattr(notify.requests, "post", fake.post)
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_EXAMPLE", "42")
    notify._alerted.clear()
    return fake


ALLOWED = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre", "blockquote",
           "tg-spoiler", "span", "tg-emoji"}


def telegram_html_errors(text: str) -> list[str]:
    """What Telegram's HTML parse mode would reject: unknown or unclosed tags, raw & < >, too long."""
    errors, stack = [], []

    class Check(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag not in ALLOWED:
                errors.append(f"tag <{tag}> not allowed")
            if tag == "a" and not dict(attrs).get("href"):
                errors.append("link without href")
            stack.append(tag)

        def handle_endtag(self, tag):
            if not stack or stack.pop() != tag:
                errors.append(f"</{tag}> closes nothing")

    Check(convert_charrefs=False).feed(text)
    if stack:
        errors.append(f"unclosed {stack}")
    if re.search(r"&(?!(?:lt|gt|amp|quot|#\d+|#x[0-9a-fA-F]+);)", text):
        errors.append("raw & (must be &amp;)")
    if len(text) > 4096:
        errors.append(f"{len(text)} characters (max 4096)")
    return errors


@pytest.fixture(autouse=True)
def no_commune_lookups(monkeypatch):
    """The archive asks geo.api.gouv.fr for unknown towns: never from the tests."""
    import requests

    import hunter.archive

    def offline(*a, **k):
        raise requests.ConnectionError("no network in tests")
    monkeypatch.setattr(hunter.archive.requests, "get", offline)


@pytest.fixture(autouse=True)
def robots_allow_everything(monkeypatch):
    """The crawlers check robots.txt before opening a page; the tests stay offline (test_robots_* checks the rule)."""
    import hunter.careers

    monkeypatch.setattr(hunter.careers, "allowed", lambda url: True)

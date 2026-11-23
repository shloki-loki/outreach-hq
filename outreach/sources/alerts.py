"""LinkedIn job-alert emails in Shlok's Gmail (Shlok, 2026-11-23: "use my LinkedIn alerts").

LinkedIn matches these jobs to his signed-in profile, so they hold the roles the logged-out search misses.
The system already reads this inbox (replies, bounces); this reads only mail from LinkedIn's alert senders,
read-only. Nothing touches his LinkedIn account.

Each job in an alert reads: title, company, location, an optional extra line, then "View job: <link>".
The link carries a one-click sign-in token, so only the job number is kept and the link is rebuilt clean.
The same inbox also has "your application was sent to <company>" mail; `applications()` reads those.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import date, timedelta
from email.header import decode_header, make_header
from typing import Any

from .. import mailbox

ALERT_SENDERS = ("jobalerts-noreply@linkedin.com", "jobs-listings@linkedin.com")
APPLIED_SENDER = "jobs-noreply@linkedin.com"
_VIEW = re.compile(r"View job:\s*https?://[^\s]*?/jobs/view/(\d{6,14})")
_NOISE = re.compile(r"^(apply with resume|easy apply|actively recruiting|fast growing|promoted|be an early applicant|"
                    r"\d+ (connection|alumni|school alum)|.*\bconnections?\b work here|new jobs match|your job alert|"
                    r"see all jobs|-{5,})", re.I)
_APPLIED = re.compile(r"your application was sent to (.+)$", re.I)


def job_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def parse_alert(text: str, sent_on: str | None = None) -> list[dict]:
    """Jobs in one alert email's plain text."""
    jobs: list[dict] = []
    lines = [line.strip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        match = _VIEW.search(line)
        if not match:
            continue
        block: list[str] = []
        for previous in reversed(lines[:index]):
            if not previous:
                if block:
                    break
                continue
            if previous.startswith("View job:") or previous.startswith("---"):
                break
            if not _NOISE.match(previous):
                block.insert(0, previous)
        if len(block) < 2:
            continue
        title, company = block[0], block[1]
        location = block[2] if len(block) > 2 else ""
        job_id = match.group(1)
        jobs.append({
            "source": "linkedin", "source_id": job_id, "via": "alert",
            "url": job_url(job_id), "apply_url": job_url(job_id),
            "company": company, "title": title, "location": location,
            "posted_at": sent_on, "description": "", "pay_text": "",
        })
    return jobs


def _plain(message: email.message.Message) -> str:
    for part in message.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", "replace")
    return ""


def _open() -> imaplib.IMAP4_SSL | None:
    if not (os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD")):
        return None
    box = mailbox.from_env("alerts")
    imap = mailbox._imap(box)
    imap.login(box.address, box.password)
    imap.select('"[Gmail]/All Mail"', readonly=True)
    return imap


def _messages(imap: imaplib.IMAP4_SSL, sender: str, since: date) -> list[email.message.Message]:
    _, data = imap.search(None, "FROM", sender, "SINCE", since.strftime("%d-%b-%Y"))
    out = []
    for number in data[0].split():
        _, parts = imap.fetch(number, "(BODY.PEEK[])")
        out.append(email.message_from_bytes(parts[0][1]))
    return out


def _sent_on(message: email.message.Message) -> str | None:
    try:
        return email.utils.parsedate_to_datetime(message["Date"]).isoformat()
    except (TypeError, ValueError):
        return None


def fetch(targeting: dict, companies: dict) -> tuple[list[dict], list[str]]:
    cfg = targeting.get("alerts") or {}
    if cfg.get("enabled") is False:
        return [], []
    try:
        imap = _open()
    except (imaplib.IMAP4.error, OSError) as exc:
        return [], [f"alerts: could not read Gmail: {type(exc).__name__}"]
    if imap is None:
        return [], []  # no Gmail on this machine: skipped quietly
    since = date.today() - timedelta(days=int(cfg.get("days", 3)))
    jobs: dict[str, dict] = {}
    try:
        for sender in ALERT_SENDERS:
            for message in _messages(imap, sender, since):
                for job in parse_alert(_plain(message), _sent_on(message)):
                    jobs.setdefault(job["source_id"], job)
    finally:
        try:
            imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
    return list(jobs.values()), []


def applications(days: int = 30) -> list[dict[str, Any]]:
    """[{company, at}] from LinkedIn's "your application was sent to <company>" mail."""
    imap = _open()
    if imap is None:
        return []
    out = []
    try:
        for message in _messages(imap, APPLIED_SENDER, date.today() - timedelta(days=days)):
            subject = str(make_header(decode_header(message["Subject"] or "")))
            match = _APPLIED.search(subject)
            if match:
                out.append({"company": match.group(1).strip(), "at": _sent_on(message)})
    finally:
        try:
            imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
    return out

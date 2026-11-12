"""Gmail over SMTP (send) and IMAP (read replies and bounces), using a Google App Password.

The App Password is read from the environment (GMAIL_ADDRESS, GMAIL_APP_PASSWORD) and is never
written to disk by this code.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr
from pathlib import Path

HEADERS = "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES X-FAILED-RECIPIENTS AUTO-SUBMITTED)])"
DAEMONS = ("mailer-daemon", "postmaster")
SENT_FOLDER = '"[Gmail]/Sent Mail"'


class NotConfigured(Exception):
    pass


@dataclass(frozen=True)
class Mailbox:
    address: str
    password: str
    name: str
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    imap_host: str = "imap.gmail.com"


def from_env(name: str) -> Mailbox:
    address, password = os.environ.get("GMAIL_ADDRESS"), os.environ.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise NotConfigured("GMAIL_ADDRESS and GMAIL_APP_PASSWORD are not set")
    return Mailbox(address=address, password=password.replace(" ", ""), name=name)


def new_message_id(box: Mailbox) -> str:
    return make_msgid(domain=box.address.rsplit("@", 1)[-1])


def build(box: Mailbox, to: str, subject: str, body: str, *, message_id: str, to_name: str = "",
          in_reply_to: str | None = None, attachment: Path | None = None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((box.name, box.address))
    message["To"] = formataddr((to_name, to)) if to_name else to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = message_id
    if in_reply_to:  # keeps a follow-up in the same thread
        message["In-Reply-To"] = in_reply_to
        message["References"] = in_reply_to
    message.set_content(body)
    if attachment:
        message.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf", filename=attachment.name)
    return message


def send(box: Mailbox, message: EmailMessage) -> None:
    with smtplib.SMTP(box.smtp_host, box.smtp_port, timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(box.address, box.password)
        smtp.send_message(message)


def check_login(box: Mailbox) -> None:
    """Log in to SMTP and IMAP without sending anything; raises on bad credentials."""
    with smtplib.SMTP(box.smtp_host, box.smtp_port, timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(box.address, box.password)
    with imaplib.IMAP4_SSL(box.imap_host, ssl_context=ssl.create_default_context()) as imap:
        imap.login(box.address, box.password)


@dataclass
class Reply:
    message_id: str          # our Message-ID that was answered ('' when matched by sender only)
    sender: str
    subject: str
    date: str
    snippet: str
    auto: bool = False


@dataclass
class InboxReport:
    replies: list[Reply] = field(default_factory=list)
    bounced: set[str] = field(default_factory=set)


def _plain_text(raw: bytes) -> str:
    message = email.message_from_bytes(raw)
    part = message
    if message.is_multipart():
        part = next((p for p in message.walk() if p.get_content_type() == "text/plain"), None) or \
               next((p for p in message.walk() if p.get_content_type() == "text/html"), message)
    payload = part.get_payload(decode=True) or b""
    text = payload.decode(part.get_content_charset() or "utf-8", "replace")
    if part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    lines = []
    for line in text.splitlines():
        if line.startswith(">") or re.match(r"^On .+ wrote:$", line.strip()):
            break  # the quoted original starts here
        lines.append(line.strip())
    return re.sub(r"\s+", " ", " ".join(lines)).strip()[:400]


def scan_inbox(box: Mailbox, since: date, message_ids: set[str], addresses: set[str], limit: int = 1500) -> InboxReport:
    """Look through INBOX since `since` for replies to our emails and bounces of them."""
    report = InboxReport()
    addresses = {a.lower() for a in addresses}
    with imaplib.IMAP4_SSL(box.imap_host, ssl_context=ssl.create_default_context()) as imap:
        imap.login(box.address, box.password)
        imap.select("INBOX", readonly=True)
        _, found = imap.search(None, "SINCE", since.strftime("%d-%b-%Y"))
        numbers = (found[0] or b"").split()[-limit:]
        if not numbers:
            return report
        _, fetched = imap.fetch(b",".join(numbers), HEADERS)
        reply_numbers: dict[bytes, Reply] = {}
        unclear_bounces: list[bytes] = []
        for item in fetched:
            if not isinstance(item, tuple):
                continue
            number = item[0].split()[0]
            headers = email.message_from_bytes(item[1])
            sender = parseaddr(headers.get("From", ""))[1].lower()
            if sender.startswith(DAEMONS):
                failed = {addr.lower() for _, addr in getaddresses([headers.get("X-Failed-Recipients", "")]) if addr}
                if failed:
                    report.bounced |= failed & addresses
                else:
                    unclear_bounces.append(number)
                continue
            threaded = set(re.findall(r"<[^<>\s]+>", f"{headers.get('In-Reply-To', '')} {headers.get('References', '')}"))
            answered = threaded & message_ids
            if answered or sender in addresses:
                auto = (headers.get("Auto-Submitted", "no").lower() != "no" or
                        bool(re.match(r"(?i)\s*(automatic reply|auto[- ]?reply|out of (the )?office|autoreply)", headers.get("Subject", ""))))
                reply_numbers[number] = Reply(message_id=sorted(answered)[0] if answered else "", sender=sender,
                                              subject=str(headers.get("Subject", ""))[:200],
                                              date=str(headers.get("Date", "")), snippet="", auto=auto)
        if unclear_bounces:  # bounce notices without X-Failed-Recipients: look for the address in the body
            _, bodies = imap.fetch(b",".join(unclear_bounces), "(BODY.PEEK[TEXT]<0.8000>)")
            for item in bodies:
                if isinstance(item, tuple):
                    text = item[1].decode("utf-8", "replace").lower()
                    report.bounced |= {a for a in addresses if a in text}
        for number, reply in reply_numbers.items():
            _, body = imap.fetch(number, "(BODY.PEEK[])")
            raw = next((part[1] for part in body if isinstance(part, tuple)), b"")
            reply.snippet = _plain_text(raw)
            report.replies.append(reply)
    return report


def in_sent_folder(box: Mailbox, message_id: str) -> bool:
    """True when Gmail's Sent folder holds this Message-ID (used to resolve an interrupted send)."""
    with imaplib.IMAP4_SSL(box.imap_host, ssl_context=ssl.create_default_context()) as imap:
        imap.login(box.address, box.password)
        status, _ = imap.select(SENT_FOLDER, readonly=True)
        if status != "OK":
            return False
        _, found = imap.search(None, "HEADER", "Message-ID", f'"{message_id}"')
        return bool((found[0] or b"").split())

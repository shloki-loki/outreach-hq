"""The morning digest: one email to Shlok with what needs him today."""

from __future__ import annotations

import os
from typing import Any

from . import mailbox, metrics, store
from .leads import display_status
from .util import load_config, now, parse_iso, today


def build() -> tuple[str, str]:
    """Returns (subject, plain-text body)."""
    leads = store.load("leads")["leads"]
    messages = store.load("messages")["messages"]
    issues = [i for i in store.load("issues")["issues"] if i.get("status") == "open"]
    numbers = metrics.compute()
    site = os.environ.get("SITE_URL", "").rstrip("/")
    by_id = {lead["id"]: lead for lead in leads}

    def label(lead: dict) -> str:
        return f"{lead['company']} · {lead['title']}"

    def link(lead: dict) -> str:
        return f"\n     {site}/lead/{lead['id']}" if site else ""

    yesterday = now().timestamp() - 86400
    replies = [m for m in messages if m.get("status") == "replied"
               and (parse_iso((m.get("reply") or {}).get("at")) or now()).timestamp() >= yesterday]
    drafts = [m for m in messages if m.get("status") == "draft"]
    due = [lead for lead in leads if lead.get("followup", {}).get("due")]
    failed = [m for m in messages if m.get("status") in ("failed", "sending")]
    bounced = [m for m in messages if m.get("status") == "bounced"
               and (parse_iso(m.get("sent_at")) or now()).timestamp() >= yesterday - 2 * 86400]
    fresh = sorted((lead for lead in leads if lead.get("stage") == "qualified" and lead.get("open", True)
                    and display_status(lead, [m for m in messages if m["lead_id"] == lead["id"]]) == "qualified"),
                   key=lambda lead: -lead.get("score", {}).get("total", 0))[:8]

    parts = [f"Outreach HQ, {now().strftime('%a %d %b')}", ""]
    if replies:
        parts.append(f"REPLIES ({len(replies)}) - answer these first")
        for message in replies:
            lead = by_id.get(message["lead_id"], {"company": "?", "title": "?", "id": ""})
            parts.append(f"  - {message['to_name'] or message['to']} at {label(lead)}")
            parts.append(f"     \"{(message['reply'] or {}).get('snippet', '')[:220]}\"{link(lead)}")
        parts.append("")
    if drafts:
        parts.append(f"WAITING FOR YOUR APPROVAL ({len(drafts)})" + (f"  {site}/approvals" if site else ""))
        for message in drafts[:12]:
            lead = by_id.get(message["lead_id"], {"company": "?", "title": "?"})
            kind = "follow-up" if message["kind"] != "cold" else "cold email"
            parts.append(f"  - {kind} to {message['to_name'] or message['to']} ({label(lead)})")
        if len(drafts) > 12:
            parts.append(f"  ... and {len(drafts) - 12} more")
        parts.append("")
    if due:
        parts.append(f"FOLLOW-UPS DUE, DRAFT NOT WRITTEN YET ({len(due)})")
        for lead in due[:10]:
            parts.append(f"  - {label(lead)} ({lead['followup'].get('kind')}){link(lead)}")
        parts.append("")
    if failed or bounced:
        parts.append("NEEDS A LOOK")
        for message in failed:
            parts.append(f"  - {message['id']} to {message['to']}: {message.get('error') or 'send was interrupted'}")
        for message in bounced:
            parts.append(f"  - bounced: {message['to']} (address marked invalid, a new one is needed)")
        parts.append("")
    if fresh:
        parts.append("TOP QUALIFIED LEADS NOT YET CONTACTED")
        for lead in fresh:
            pay = lead.get("pay", {}).get("fit", "Unknown")
            parts.append(f"  - {lead['score']['total']:>3}  {label(lead)} · {lead.get('location', '')} · pay: {pay}{link(lead)}")
        parts.append("")
    parts.append("NUMBERS")
    parts.append(f"  Leads: {numbers['leads_total']} total, {numbers['qualified_total']} qualified, "
                 f"{numbers['new_leads_7d']} new in 7 days")
    parts.append(f"  Emails: {numbers['emails_sent_total']} sent, {numbers['people_replied']} people replied, "
                 f"{numbers['bounces_total']} bounced")
    rate = f"{numbers['reply_rate'] * 100:.0f}%" if numbers["reply_rate"] is not None else "n/a"
    parts.append(f"  Reply rate: {rate} · Applied: {numbers['applied_total']} · Interviews: {numbers['interviews']} "
                 f"· Offers: {numbers['offers']}")
    if issues:
        parts += ["", f"OPEN ISSUES ({len(issues)})"]
        for issue in issues[:6]:
            parts.append(f"  - [{issue['severity']}] {issue['title']}")
    if not (replies or drafts or due or failed or bounced):
        parts.insert(2, "Nothing needs you this morning.\n")

    bits = []
    if replies:
        bits.append(f"{len(replies)} repl{'y' if len(replies) == 1 else 'ies'}")
    if drafts:
        bits.append(f"{len(drafts)} to approve")
    if due:
        bits.append(f"{len(due)} follow-up{'s' if len(due) != 1 else ''} due")
    subject = f"Outreach HQ {now().strftime('%d %b')}: " + (", ".join(bits) if bits else "all clear")
    return subject, "\n".join(parts) + "\n"


def run(print_only: bool = False) -> dict[str, Any]:
    store.sync()
    subject, body = build()
    if print_only:
        return {"subject": subject, "body": body, "sent": False}
    settings = load_config("settings")
    try:
        box = mailbox.from_env("Outreach HQ")
    except mailbox.NotConfigured as exc:
        store.log_run("follow-up/digest", False, str(exc))
        return {"subject": subject, "body": body, "sent": False, "note": str(exc)}
    mail = mailbox.build(box, settings["digest"]["send_to"], subject, body, message_id=mailbox.new_message_id(box))
    mailbox.send(box, mail)  # a note to yourself; not outreach, so it does not wait for approval
    store.log_run("follow-up/digest", True, subject)
    return {"subject": subject, "body": body, "sent": True}

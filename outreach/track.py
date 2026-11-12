"""The tracker: reads the inbox for replies and bounces, settles interrupted sends, and decides
which leads are due a follow-up. It changes statuses; it never sends anything.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from . import emailfinder, mailbox, store
from .util import business_days_between, load_config, now, now_iso, parse_iso

OPEN_STATES = ("sent",)


def scan(box: mailbox.Mailbox | None) -> dict[str, Any]:
    settings = load_config("settings")
    stats = {"replies": 0, "auto_replies": 0, "bounces": 0, "settled": 0, "followups_due": 0}
    messages = store.load("messages")["messages"]
    outstanding = [m for m in messages if m.get("status") in ("sent", "sending") and m.get("message_id")]

    report = mailbox.InboxReport()
    settled: dict[str, bool] = {}
    if box and outstanding:
        since = (now() - timedelta(days=settings["tracking"]["inbox_lookback_days"])).date()
        report = mailbox.scan_inbox(box, since, {m["message_id"] for m in outstanding},
                                    {m["to"] for m in outstanding})
        for message in outstanding:
            if message["status"] != "sending":
                continue
            started = parse_iso(message.get("sending_at"))
            if started and (now() - started) > timedelta(minutes=10):  # an interrupted send
                settled[message["id"]] = mailbox.in_sent_folder(box, message["message_id"])

    learned_bounce: list[tuple[str, str]] = []
    learned_reply: list[tuple[str, str]] = []

    def change() -> None:
        for key in stats:
            stats[key] = 0
        learned_bounce.clear()
        learned_reply.clear()
        data, leads, suppression = store.load("messages"), store.load("leads"), store.load("suppression")
        by_rfc = {m["message_id"]: m for m in data["messages"] if m.get("message_id")}

        for message_id, was_sent in settled.items():
            message = store.find(data["messages"], message_id)
            if not message or message.get("status") != "sending":
                continue
            lead = store.find(leads["leads"], message["lead_id"])
            if was_sent:
                message.update(status="sent", sent_at=message.get("sending_at"), error=None)
                if lead:
                    lead["first_contacted_at"] = lead.get("first_contacted_at") or message["sent_at"]
                    store.add_timeline(lead, "send-track", "sent", "confirmed in Gmail's Sent folder after an interrupted run")
            else:
                message.update(status="failed", error="The send was interrupted and the email is not in Gmail's Sent "
                                                      "folder. Press Retry to queue it again.")
            stats["settled"] += 1

        for reply in report.replies:
            target = by_rfc.get(reply.message_id) or next(
                (m for m in sorted(data["messages"], key=lambda m: m.get("sent_at") or "", reverse=True)
                 if m.get("to", "").lower() == reply.sender and m.get("status") in ("sent", "replied")), None)
            if not target or (target.get("reply") or {}).get("date") == reply.date:
                continue
            lead = store.find(leads["leads"], target["lead_id"])
            if reply.auto:
                if not target.get("auto_reply"):
                    target["auto_reply"] = {"at": now_iso(), "subject": reply.subject, "snippet": reply.snippet}
                    stats["auto_replies"] += 1
                    if lead:
                        store.add_timeline(lead, "follow-up", "auto_reply", f"{reply.sender}: {reply.subject}")
                continue
            if target.get("status") == "replied":
                continue
            target["status"] = "replied"
            target["reply"] = {"at": now_iso(), "from": reply.sender, "subject": reply.subject,
                               "date": reply.date, "snippet": reply.snippet}
            stats["replies"] += 1
            learned_reply.append((target["to"], target.get("to_name") or ""))
            if lead:
                lead["replied_at"] = lead.get("replied_at") or now_iso()
                lead["followup"] = {"due": False, "kind": None, "since": None}
                store.add_timeline(lead, "follow-up", "replied", f"{reply.sender}: {reply.snippet[:160]}")
                for contact in lead.get("contacts", []):
                    if contact.get("email") == target["to"]:
                        contact["email_status"] = "verified"
            # A reply ends the thread: drop anything still queued for that person.
            for other in data["messages"]:
                if other["lead_id"] == target["lead_id"] and other["contact_id"] == target["contact_id"] \
                        and other.get("status") in ("draft", "approved"):
                    other.update(status="skipped", error="They replied; the queued message was dropped.")

        for address in report.bounced:
            for message in data["messages"]:
                if message.get("to", "").lower() != address or message.get("status") not in ("sent", "sending"):
                    continue
                message["status"] = "bounced"
                stats["bounces"] += 1
                learned_bounce.append((address, message.get("to_name") or ""))
                lead = store.find(leads["leads"], message["lead_id"])
                if lead:
                    for contact in lead.get("contacts", []):
                        if contact.get("email") == address:
                            contact["email_status"] = "bounced"
                            contact["confidence"] = 0
                    store.add_timeline(lead, "follow-up", "bounced", f"{address} does not exist; needs a new address")
            suppression["emails"][address] = {"reason": "hard bounce", "at": now_iso()}

        stats["followups_due"] = _mark_followups(data["messages"], leads["leads"], settings)
        store.save("messages", data)
        store.save("leads", leads)
        store.save("suppression", suppression)

    store.transact(change, "track: inbox scan")
    for address, name in learned_bounce:
        emailfinder.learn_bounce(address, name)
    for address, name in learned_reply:
        emailfinder.learn_delivered(address, name)
    return stats


def _mark_followups(messages: list[dict], leads: list[dict], settings: dict) -> int:
    """Set lead.followup for every thread that has gone quiet long enough. Returns how many are due."""
    cfg = settings["followups"]
    due_count = 0
    for lead in leads:
        closed = lead.get("replied_at") or lead.get("outcome") in ("offer", "rejected", "closed") \
            or lead.get("stage") in ("rejected", "skipped")
        mine = [m for m in messages if m.get("lead_id") == lead["id"]]
        due: dict[str, Any] = {"due": False, "kind": None, "since": None}
        if not closed:
            for contact_id in {m["contact_id"] for m in mine}:
                thread = [m for m in mine if m["contact_id"] == contact_id]
                if any(m.get("status") in ("replied", "bounced") for m in thread):
                    continue
                if any(m.get("status") in ("draft", "approved", "sending") for m in thread):
                    continue  # something is already queued for this person
                sent = sorted((m for m in thread if m.get("status") == "sent"), key=lambda m: m.get("sent_at") or "")
                if not sent:
                    continue
                kinds = {m["kind"] for m in sent}
                last = parse_iso(sent[-1].get("sent_at"))
                if not last:
                    continue
                quiet = business_days_between(last, now())
                if any(m.get("auto_reply") for m in thread):
                    quiet -= 3  # out of office: give them a few more days
                next_kind = None
                if "followup1" not in kinds and cfg["max_followups"] >= 1 and quiet >= cfg["first_after_business_days"]:
                    next_kind = "followup1"
                elif "followup1" in kinds and "followup2" not in kinds and cfg["max_followups"] >= 2 \
                        and quiet >= cfg["second_after_business_days"]:
                    next_kind = "followup2"
                if next_kind:
                    previous = lead.get("followup") or {}
                    due = {"due": True, "kind": next_kind, "contact_id": contact_id,
                           "since": previous.get("since") if previous.get("due") else now_iso()}
                    break
        if due["due"]:
            due_count += 1
        if (lead.get("followup") or {}).get("due") != due["due"] or (lead.get("followup") or {}).get("kind") != due["kind"]:
            lead["followup"] = due
            if due["due"]:
                store.add_timeline(lead, "follow-up", "followup_due", f"{due['kind']} is due")
    return due_count


def run() -> dict[str, Any]:
    store.sync()
    box = None
    try:
        box = mailbox.from_env(load_config("profile")["person"]["name"])
    except mailbox.NotConfigured:
        pass
    try:
        stats = scan(box)
    except Exception as exc:
        store.log_run("follow-up/track", False, f"inbox scan failed: {type(exc).__name__}: {exc}")
        store.open_issue("follow-up", "Inbox scan failed", f"{type(exc).__name__}: {exc}", severity="error",
                         key="inbox-scan-failed")
        raise
    note = "" if box else " (Gmail not connected: follow-up timers only, no reply or bounce detection)"
    store.log_run("follow-up/track", True,
                  f"{stats['replies']} replies, {stats['bounces']} bounces, {stats['followups_due']} follow-ups due{note}", stats)
    return stats

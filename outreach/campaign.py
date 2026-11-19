"""Template campaigns: one text Shlok approved in chat, filled with each person's first name and company.

Why this exists: on 2026-11-19 Shlok asked for the founder list to be worked through with a template instead
of researched one-by-one emails, sent without a per-email click. He approved the exact text
(config/templates/founder-v1.toml), 60 a day, and every listed address at each company.

What still applies to every message, because the normal sender sends them: the daily caps and window,
pauses between sends, the do-not-email list, one cold email per address in `one_email_per_person_days`,
bounced/invalid addresses, trusted addresses only, and reply/bounce tracking. Queueing tops up to the
template's `per_day` each day, so a stop takes effect within a day at most (`campaign stop` is immediate).
"""

from __future__ import annotations

import re
import tomllib
from typing import Any

from . import store
from .messages import TRUSTED, recently_contacted
from .util import CONFIG_DIR, load_config, now_iso, today

LEGAL = re.compile(r"\s*\((?:[^)]*)\)|,?\s+(?:pvt\.?|private|ltd\.?|limited|inc\.?|llp|llc)\b\.?", re.I)
PAY = re.compile(r"\b(ctc|lpa|salary|notice period|stipend)\b", re.I)


def load(template_id: str) -> dict[str, Any]:
    with open(CONFIG_DIR / "templates" / f"{template_id}.toml", "rb") as handle:
        template = tomllib.load(handle)
    if template.get("id") != template_id:
        raise ValueError(f"template file {template_id}.toml has id {template.get('id')!r}")
    return template


def company_name(raw: str) -> str:
    """'Acme Technologies Pvt Ltd (YC W21)' -> 'Acme Technologies'."""
    name = LEGAL.sub("", raw or "").strip(" ,.-")
    return re.sub(r"\s{2,}", " ", name)


def first_name(raw: str) -> str:
    parts = [p for p in re.split(r"\s+", (raw or "").strip()) if p and not re.fullmatch(r"(?i)(dr|mr|ms|mrs)\.?", p)]
    return parts[0].strip(".,") if parts else ""


def role_name(raw: str) -> str:
    """'Strategy & Ops (Founder's Office) - Bengaluru | Hiring' -> 'Strategy & Ops (Founder's Office)'."""
    role = re.split(r"\s+[|\u2013\u2014]\s+|\s+-\s+(?=[A-Z][a-z]+(?:,|$))", raw or "")[0].strip(" ,.-")
    return role if len(role) <= 70 else ""


def render(template: dict, contact: dict, lead: dict, kind: str = "") -> tuple[str, str]:
    fields = {"first_name": first_name(contact.get("name", "")), "company": company_name(lead.get("company", "")),
              "role": role_name(lead.get("title", ""))}
    if not fields["first_name"] and template.get("audience") == "jobs":
        fields["first_name"] = "there"     # a hiring inbox such as careers@ has no person's name
    if not fields["first_name"] or not fields["company"]:
        raise ValueError("missing first name or company")
    if "{role}" in template.get("subject", "") + template.get("body", "") and not fields["role"]:
        raise ValueError("role title missing or too long to quote")
    body = template[f"body_{kind}"] if kind else template["body"]
    return template.get("subject", "").format(**fields), body.format(**fields)


def check(subject: str, body: str, first: str, company: str) -> list[str]:
    """What a filled template must still satisfy (the text itself was approved as a whole)."""
    problems = []
    if re.search(r"[{}]", subject + body):
        problems.append("a placeholder was not filled")
    if not body.startswith(f"Hi {first},"):
        problems.append("greeting does not use the first name")
    if company not in body:
        problems.append("company name missing from the body")
    if "beltech" in (subject + body).lower():
        problems.append("mentions Beltech")
    if PAY.search(body):
        problems.append("mentions pay or notice period")
    if "—" in body or "!" in body:
        problems.append("em dash or exclamation mark")
    if body.rstrip().splitlines()[-1].strip() != "Shlok":
        problems.append("last line is not 'Shlok'")
    if len(subject) > 80:
        problems.append("subject longer than 80 characters")
    return problems


def targets(template: dict, leads: list[dict], messages: list[dict], days: int) -> list[tuple[dict, dict]]:
    """Every eligible (lead, contact): CEO/founders first within a company, best-scored companies first, round-robin."""
    out = []
    taken = {m.get("to", "").lower() for m in messages if m.get("kind") == "cold" and m.get("status") != "skipped"}
    blocked = {e.lower() for e in store.load("suppression")["emails"]}
    jobs = template.get("audience") == "jobs"
    per_lead = int(template.get("per_lead", 99))
    pool = [l for l in leads if l.get("open", True) is not False and l.get("outcome") not in ("rejected", "closed")
            and not l.get("replied_at") and (
                (l.get("type") == "job" and l.get("stage") == "qualified" and not l.get("applied_at")
                 and not any(m.get("lead_id") == l["id"] and m.get("kind") == "cold" and m.get("status") != "skipped"
                             for m in messages)) if jobs else
                (l.get("source") == template["source"] and l.get("type") == "company"
                 and l.get("stage") not in ("rejected", "skipped")))]
    pool.sort(key=lambda l: (-((l.get("score") or {}).get("total") or 0), l["id"]))
    for rank, lead in enumerate(pool):
        contacts = sorted(lead.get("contacts", []), key=lambda c: (
            (0 if c.get("role_type") == "hiring_manager" else 1 if c.get("role_type") == "founder" else
             2 if c.get("role_type") == "recruiter" else 3) if jobs else
            0 if re.search(r"\b(ceo|chief executive|managing director)\b", c.get("title") or "", re.I) else
            1 if c.get("role_type") == "founder" else 2, c.get("id", "")))
        seen = set()
        for contact in contacts:
            email = (contact.get("email") or "").lower()
            if not email or email in seen or email in taken or contact.get("email_status") not in TRUSTED:
                continue
            if email in blocked or recently_contacted(email, messages, days) or len(seen) >= per_lead:
                continue
            seen.add(email)
            out.append((len(seen) - 1, rank, lead, contact))
    # Round-robin: every company's first person before anyone's second, so co-founders don't get the same
    # text in the same hour and the whole list is reached sooner.
    out.sort(key=lambda t: (t[0], t[1]))
    return [(lead, contact) for _, _, lead, contact in out]


def queue(template_id: str, limit: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Top up today's approved messages from this template to its per_day (or `limit`)."""
    template = load(template_id)
    if not template.get("active"):
        return {"template": template_id, "queued": 0, "note": "template is not active"}
    settings = load_config("settings")
    days = int(settings["sending"]["one_email_per_person_days"])
    result: dict[str, Any] = {}

    def change() -> None:
        result.clear()
        leads, data = store.load("leads"), store.load("messages")
        mine = [m for m in data["messages"] if m.get("template") == template_id]
        today_count = sum(1 for m in mine if (m.get("approved_at") or "").startswith(today()))
        waiting = sum(1 for m in mine if m.get("status") == "approved")
        cap = template.get("per_day", 60) if limit is None else limit
        room = max(0, cap - max(today_count, waiting))
        eligible = targets(template, leads["leads"], data["messages"], days)
        queued, refused = [], []
        for lead, contact in eligible:
            if len(queued) >= room:
                break
            try:
                subject, body = render(template, contact, lead)
            except ValueError as exc:
                refused.append(f"{lead['id']}/{contact.get('id')}: {exc}")
                continue
            problems = check(subject, body, first_name(contact.get("name", "")) or "there", company_name(lead.get("company", "")))
            if problems:
                refused.append(f"{lead['id']}/{contact.get('id')}: {'; '.join(problems)}")
                continue
            stamp = now_iso()
            message = {
                "id": store.next_id(data["messages"], "M"), "lead_id": lead["id"], "contact_id": contact["id"],
                "to": contact["email"].lower(), "to_name": contact.get("name") or "", "kind": "cold",
                "subject": subject, "body": body.rstrip() + "\n", "status": "approved",
                "email_status": contact.get("email_status"), "speculative": lead.get("type") == "company",
                "hook": "", "hook_source": "", "play": "template", "promise": "", "playbook": f"template:{template_id}",
                "template": template_id, "attach_resume": False,
                "created_at": stamp, "created_by": "campaign", "approved_at": stamp,
                "approved_by": f"template {template_id} ({template.get('approved_by', '')})",
                "sending_at": None, "sent_at": None, "message_id": None, "thread_parent": None, "error": None,
                "reply": None,
            }
            data["messages"].append(message)
            store.add_timeline(lead, "campaign", "drafted",
                               f"template {template_id} email to {contact.get('name')} queued (approved in chat)")
            queued.append(message["id"])
        result.update(template=template_id, queued=len(queued), ids=queued, room=room,
                      left_after=len(eligible) - len(queued), refused=refused[:20], dry_run=dry_run)
        if queued and not dry_run:
            store.save("messages", data)
            store.save("leads", leads)
            store.journal("campaign", "update", f"Template {template_id}: {len(queued)} emails queued",
                          f"{len(eligible) - len(queued)} addresses left after today; refused {len(refused)}", queued[0])

    if dry_run:
        with store.locked():
            store.sync()
            change()
    else:
        store.transact(change, f"campaign: queue {template_id}")
    return result


def stop(template_id: str) -> dict[str, Any]:
    """Pull back every approved, unsent message of this template at once."""
    pulled: list[str] = []

    def change() -> None:
        pulled.clear()
        data = store.load("messages")
        for message in data["messages"]:
            if message.get("template") == template_id and message.get("status") == "approved":
                message.update(status="skipped", error="campaign stopped")
                pulled.append(message["id"])
        if pulled:
            store.save("messages", data)
            store.journal("campaign", "update", f"Template {template_id} stopped",
                          f"{len(pulled)} approved emails pulled back before sending", pulled[0])
    store.transact(change, f"campaign: stop {template_id}")
    return {"template": template_id, "pulled_back": len(pulled)}


def status(template_id: str) -> dict[str, Any]:
    template = load(template_id)
    with store.locked():
        store.sync()
        leads, messages = store.load("leads")["leads"], store.load("messages")["messages"]
    mine = [m for m in messages if m.get("template") == template_id]
    counts: dict[str, int] = {}
    for m in mine:
        counts[m["status"]] = counts.get(m["status"], 0) + 1
    days = int(load_config("settings")["sending"]["one_email_per_person_days"])
    left = len(targets(template, leads, messages, days))
    return {"template": template_id, "active": bool(template.get("active")), "per_day": template.get("per_day"),
            "by_status": counts, "addresses_left": left, "days_left_at_cap": -(-left // max(1, template.get("per_day", 60)))}


def queue_followups(template_id: str = "followup-v1") -> dict[str, Any]:
    """Queue the generic follow-ups (approved by Shlok as text) for every quiet thread: job emails and founder emails.

    Same timing as the tracker: followup1 after `first_after_business_days` of silence, followup2 after
    `second_after_business_days` more. Never after a reply, a bounce, an out-of-office still running, a closed
    lead, or while something else is queued for that person. Sent in the same thread. Capped per day."""
    template = load(template_id)
    if not template.get("active"):
        return {"template": template_id, "queued": 0, "note": "template is not active"}
    from .util import business_days_between, now, parse_iso
    settings = load_config("settings")
    cfg, cap = settings["followups"], int(settings["sending"]["followups_per_day"])
    result: dict[str, Any] = {}

    def change() -> None:
        result.clear()
        leads, data = store.load("leads"), store.load("messages")
        blocked = {e.lower() for e in store.load("suppression")["emails"]}
        today_count = sum(1 for m in data["messages"] if m.get("template") == template_id
                          and (m.get("approved_at") or "").startswith(today()))
        room = max(0, cap - today_count)
        queued: list[str] = []
        by_lead = {l["id"]: l for l in leads["leads"]}
        threads: dict[tuple[str, str], list[dict]] = {}
        for m in data["messages"]:
            threads.setdefault((m.get("lead_id"), m.get("contact_id")), []).append(m)
        for (lead_id, contact_id), thread in sorted(threads.items(), key=lambda kv: min(m.get("sent_at") or "~" for m in kv[1])):
            if len(queued) >= room:
                break
            lead = by_lead.get(lead_id)
            if not lead or lead.get("replied_at") or lead.get("outcome") in ("offer", "rejected", "closed") \
                    or lead.get("stage") in ("rejected", "skipped"):
                continue
            if any(m.get("status") in ("replied", "bounced", "draft", "approved", "sending") for m in thread):
                continue
            sent = sorted((m for m in thread if m.get("status") == "sent"), key=lambda m: m.get("sent_at") or "")
            cold = next((m for m in sent if m.get("kind") == "cold"), None)
            if not cold or not cold.get("message_id") or (cold.get("to") or "").lower() in blocked:
                continue
            kinds = {m["kind"] for m in sent}
            quiet = business_days_between(parse_iso(sent[-1]["sent_at"]), now())
            if any(m.get("auto_reply") for m in thread):
                quiet -= 3
            if "followup1" not in kinds and quiet >= cfg["first_after_business_days"]:
                kind = "followup1"
            elif "followup1" in kinds and "followup2" not in kinds and quiet >= cfg["second_after_business_days"]:
                kind = "followup2"
            else:
                continue
            contact = store.find(lead.get("contacts", []), contact_id) or {"name": cold.get("to_name", "")}
            try:
                _, body = render(template, contact, lead, kind)
            except ValueError:
                continue
            problems = [p for p in check("", body, first_name(contact.get("name", "")), company_name(lead.get("company", "")))
                        if not p.startswith("company name")]
            if problems:
                continue
            stamp = now_iso()
            message = {
                "id": store.next_id(data["messages"], "M"), "lead_id": lead_id, "contact_id": contact_id,
                "to": cold["to"], "to_name": cold.get("to_name", ""), "kind": kind,
                "subject": "Re: " + re.sub(r"(?i)^(re:\s*)+", "", cold["subject"]), "body": body.rstrip() + "\n",
                "status": "approved", "email_status": cold.get("email_status"), "speculative": cold.get("speculative"),
                "hook": "", "hook_source": "", "play": "template", "promise": "", "playbook": f"template:{template_id}",
                "template": template_id, "attach_resume": False, "created_at": stamp, "created_by": "campaign",
                "approved_at": stamp, "approved_by": f"template {template_id} ({template.get('approved_by', '')})",
                "sending_at": None, "sent_at": None, "message_id": None, "thread_parent": cold["message_id"],
                "error": None, "reply": None,
            }
            data["messages"].append(message)
            lead["followup"] = {"due": False, "kind": None, "since": None}
            store.add_timeline(lead, "campaign", "drafted", f"{kind} to {cold.get('to_name') or cold['to']} queued (template)")
            queued.append(message["id"])
        result.update(template=template_id, queued=len(queued), ids=queued, room=room)
        if queued:
            store.save("messages", data)
            store.save("leads", leads)
            store.journal("campaign", "update", f"Follow-ups: {len(queued)} queued", "generic follow-up template", queued[0])

    store.transact(change, f"campaign: follow-ups {template_id}")
    return result


def queue_all() -> dict[str, Any]:
    """Every active template's daily top-up, then the follow-ups. Run before each send so the Mac or GitHub,
    whichever runs first on a day, keeps the queue full. One template's failure never stops the others."""
    out: dict[str, Any] = {}
    for path in sorted((CONFIG_DIR / "templates").glob("*.toml")):
        try:
            template = load(path.stem)
            if not template.get("active"):
                continue
            out[path.stem] = (queue_followups(path.stem) if template.get("audience") == "followups"
                              else queue(path.stem))
            out[path.stem].pop("ids", None)
        except Exception as exc:  # noqa: BLE001 - reported in the run output, the sender still runs
            out[path.stem] = {"error": f"{type(exc).__name__}: {exc}"}
    return out

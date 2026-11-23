"""The lead record and the one place that decides a lead's display status."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from . import store
from .rules import Verdict
from .util import clip, norm_company, norm_title, now_iso, today

# Job descriptions are kept up to this length (was 3,000, which cut off "8+ years" in the requirements).
JD_MAX = 8000

STAGES = ("new", "qualified", "rejected", "skipped")
OUTCOMES = (None, "interview", "offer", "rejected", "closed")
# Display statuses, most advanced first. The website mirrors this in web/lib/status.js.
STATUSES = ("offer", "interview", "replied", "followup_due", "contacted", "applied",
            "to_approve", "qualified", "new", "rejected", "closed", "skipped")


def lead_key(company: str, title: str, bucket: str = "") -> str:
    core = re.sub(r"\(.*?\)|\[.*?\]", " ", title or "")
    return f"{norm_company(company)}|{norm_title(core)}|{bucket}"


def new_lead(job: dict[str, Any], verdict: Verdict, ident: str) -> dict[str, Any]:
    contacts = []
    for index, person in enumerate(job.get("contacts") or [], 1):
        contacts.append(new_contact(person, f"C{index}"))
    return {
        "id": ident,
        "legacy_id": job.get("legacy_id"),
        "key": lead_key(job.get("company", ""), job.get("title", ""), verdict.location_bucket),
        "type": job.get("type", "job"),
        "company": (job.get("company") or "").strip(),
        "company_domain": job.get("company_domain") or "",
        "company_url": job.get("company_url") or "",
        "company_linkedin": job.get("company_linkedin") or "",
        "company_note": job.get("company_note") or "",
        "title": (job.get("title") or "").strip(),
        "tier": verdict.tier,
        "location": job.get("location") or "",
        "location_bucket": verdict.location_bucket,
        "work_mode": job.get("work_mode") or "",
        "source": job.get("source"),
        "source_id": job.get("source_id"),
        "source_url": job.get("url") or "",
        "apply_url": job.get("apply_url") or job.get("url") or "",
        "sources": [{"source": job.get("source"), "url": job.get("url") or "", "seen": today()}],
        "posted_at": job.get("posted_at"),
        "first_seen": today(),
        "last_seen": today(),
        "open": True,
        "jd": clip(job.get("description"), JD_MAX),
        "exp_min": verdict.exp_min,
        "exp_max": verdict.exp_max,
        "exp_text": job.get("experience_text") or "",
        "stretch": verdict.stretch,
        "pay": asdict(verdict.pay),
        "score": {"rules": verdict.score, "research": None, "total": verdict.score, "reasons": verdict.reasons},
        "research": {"done": False, "fit_notes": "", "pay_notes": "", "culture_notes": "", "hook": "",
                     "hook_source": "", "researched_at": None},
        "stage": "new",
        "outcome": None,
        "applied_at": None,
        "apply": {"status": "not_started", "notes": "", "answers": {}},
        "first_contacted_at": None,
        "replied_at": None,
        "contacts": contacts,
        "referrals": [],
        "followup": {"due": False, "kind": None, "since": None},
        "notes": [],
        "timeline": [{"at": now_iso(), "actor": "lead-scout", "event": "found",
                      "detail": f"{job.get('source')}: rule score {verdict.score}"}],
        "updated_at": now_iso(),
    }


def new_contact(person: dict[str, Any], ident: str) -> dict[str, Any]:
    return {
        "id": ident,
        "name": (person.get("name") or "").strip(),
        "title": person.get("title") or "",
        "role_type": person.get("role_type") or "employee",  # recruiter|hiring_manager|founder|employee|generic
        "linkedin_url": person.get("linkedin_url") or "",
        "email": (person.get("email") or "").lower(),
        "email_status": person.get("email_status") or ("published" if person.get("email") else "none"),
        "email_source": person.get("email_source") or "",
        "confidence": person.get("confidence") or 0,
        "why": person.get("why") or "",
        "found_at": now_iso(),
    }


def next_contact_id(lead: dict) -> str:
    numbers = [int(c["id"][1:]) for c in lead.get("contacts", []) if c.get("id", "")[1:].isdigit()]
    return f"C{max(numbers, default=0) + 1}"


def merge_job(lead: dict, job: dict, verdict: Verdict) -> bool:
    """Fold a re-sighting of a known job into its lead. Returns True if anything changed."""
    changed = False
    if lead.get("last_seen") != today():
        lead["last_seen"] = today()
        changed = True
    known = {(entry.get("source"), entry.get("url")) for entry in lead.get("sources", [])}
    if (job.get("source"), job.get("url") or "") not in known:
        lead.setdefault("sources", []).append({"source": job.get("source"), "url": job.get("url") or "", "seen": today()})
        changed = True
    if not lead.get("jd") and job.get("description"):
        lead["jd"] = clip(job["description"], JD_MAX)
        changed = True
    if lead.get("pay", {}).get("basis") == "unknown" and verdict.pay.basis == "stated":
        lead["pay"] = asdict(verdict.pay)
        changed = True
    if not lead.get("open", True):
        lead["open"] = True
        store.add_timeline(lead, "lead-scout", "reopened", "posting is live again")
        changed = True
    existing = {(c.get("name") or "").lower() for c in lead.get("contacts", [])}
    for person in job.get("contacts") or []:
        if person.get("name") and person["name"].lower() not in existing:
            lead.setdefault("contacts", []).append(new_contact(person, next_contact_id(lead)))
            changed = True
    return changed


def display_status(lead: dict, messages: list[dict]) -> str:
    """One status per lead for colour coding. `messages` are this lead's messages."""
    if lead.get("stage") == "skipped":
        return "skipped"
    if lead.get("outcome") in ("offer", "interview", "rejected", "closed"):
        return lead["outcome"]
    if lead.get("stage") == "rejected":
        return "rejected"
    if lead.get("replied_at") or any(m.get("status") == "replied" for m in messages):
        return "replied"
    if lead.get("followup", {}).get("due"):
        return "followup_due"
    if any(m.get("status") in ("draft", "approved", "sending", "failed") for m in messages):
        return "to_approve"
    sent = any(m.get("status") == "sent" for m in messages) or any(
        r.get("status") == "sent" for r in lead.get("referrals", []))
    if sent or lead.get("first_contacted_at"):
        return "contacted"
    if lead.get("applied_at"):
        return "applied"
    return "qualified" if lead.get("stage") == "qualified" else "new"

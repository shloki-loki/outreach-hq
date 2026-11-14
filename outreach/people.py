"""People at each qualified lead's company, found on LinkedIn through an Apify actor (no login, no cookies).

Up to 3 people per lead, in the order voice.md asks for: the person the role reports to (Chief of Staff,
founder's office, strategy or business head, COO), a founder or CEO, and the recruiter. They are added as
contacts with their LinkedIn URL so the writer can draft a connection note and an InMail for each, which Shlok
sends by hand. Nothing is ever sent on LinkedIn by this system.

Cost: harvestapi/linkedin-company-employees in Short mode, about $0.044 per company (start fee + 6 profiles),
inside the Apify monthly cap (sources/apify.py).
"""

from __future__ import annotations

import re
from typing import Any

from . import leads as lead_model
from . import live, store
from .sources.apify import BudgetSpent, run_actor, token
from .util import HttpError, now_iso

ACTOR = "harvestapi/linkedin-company-employees"
TITLES = ["Chief of Staff", "Founder's Office", "Head of Strategy", "Business Head", "Chief Operating Officer",
          "Head of Operations", "Founder", "Co-Founder", "CEO", "Talent Acquisition", "Recruiter"]

BUCKETS = [  # (bucket, role_type, pattern) checked in order
    ("reports_to", "hiring_manager", r"chief of staff|founder'?s office|ceo'?s office|head of (strategy|business|growth|operations)|"
                                     r"business head|\bcoo\b|chief operating|vp,? (strategy|operations|business)|director,? (strategy|operations)"),
    ("founder", "founder", r"\b(co-?founder|founder|ceo|chief executive|managing director)\b"),
    ("recruiter", "recruiter", r"talent|recruit|\bhr\b|human resources|people (ops|partner|team)"),
]


def bucket(title: str) -> tuple[str, str] | None:
    for name, role_type, pattern in BUCKETS:
        if re.search(pattern, title or "", re.I):
            return name, role_type
    return None


def company_url(lead: dict) -> str:
    url = (lead.get("company_linkedin") or "").strip()
    match = re.search(r"linkedin\.com/company/([^/?#]+)", url)
    return f"https://www.linkedin.com/company/{match.group(1)}" if match else ""


def choose(items: list[dict], company: str) -> list[dict]:
    """Best person per bucket, current position at this company only."""
    picked: dict[str, dict] = {}
    for item in items:
        positions = [p for p in item.get("currentPositions") or [] if p.get("current", True)]
        position = next((p for p in positions if company.lower().split()[0] in (p.get("companyName") or "").lower()),
                        positions[0] if positions else None)
        if not position or not item.get("linkedinUrl"):
            continue
        found = bucket(position.get("title") or "")
        if not found or found[0] in picked:
            continue
        picked[found[0]] = {
            "name": f"{item.get('firstName', '')} {item.get('lastName', '')}".strip(), "title": position.get("title"),
            "role_type": found[1], "linkedin_url": item["linkedinUrl"],
            "location": (item.get("location") or {}).get("linkedinText", ""),
            "why": {"reports_to": "likely reports-to or runs the function this role sits in (LinkedIn title)",
                    "founder": "founder or CEO (LinkedIn title)",
                    "recruiter": "recruits for the company (LinkedIn title)"}[found[0]],
        }
    return [picked[name] for name in ("reports_to", "founder", "recruiter") if name in picked]


def due(lead: dict) -> bool:
    return (lead.get("stage") == "qualified" and lead.get("open") is not False and not live.in_conversation(lead)
            and bool(company_url(lead)) and not lead.get("people_searched_at")
            and sum(1 for c in lead.get("contacts", []) if c.get("linkedin_url")) < 3)


def run(limit: int = 8, ids: list[str] | None = None) -> dict[str, Any]:
    store.sync()
    stats = {"leads": 0, "people_added": 0, "skipped": ""}
    if not token():
        return {**stats, "skipped": "APIFY_TOKEN is not set"}
    leads = [l for l in store.load("leads")["leads"] if (l["id"] in ids if ids else due(l))]
    leads.sort(key=lambda lead: -(lead.get("score") or {}).get("total", 0))
    for lead in leads[:limit]:
        try:
            items = run_actor(ACTOR, {"companies": [company_url(lead)], "profileScraperMode": "Short ($4 per 1k)",
                                      "maxItems": 6, "jobTitles": TITLES, "locations": ["India"]}, max_usd=0.06, timeout=120)
        except BudgetSpent as exc:
            stats["skipped"] = str(exc)
            break
        except (HttpError, ValueError) as exc:
            store.log_entry("people-finder", "debug", f"LinkedIn people search failed for {lead['company']}", str(exc)[:400], lead["id"])
            continue
        people = choose(items, lead.get("company") or "")
        added = _add(lead["id"], people)
        stats["leads"] += 1
        stats["people_added"] += added
    store.log_run("people-finder", True, f"{stats['leads']} companies searched on LinkedIn, {stats['people_added']} people added"
                  + (f"; stopped: {stats['skipped']}" if stats["skipped"] else ""), stats)
    return stats


def _add(lead_id: str, people: list[dict]) -> int:
    count = 0

    def change() -> None:
        nonlocal count
        count = 0
        data = store.load("leads")
        lead = store.find(data["leads"], lead_id)
        if not lead:
            return
        known = {(c.get("name") or "").lower() for c in lead.get("contacts", [])}
        known_urls = {c.get("linkedin_url") for c in lead.get("contacts", []) if c.get("linkedin_url")}
        for person in people:
            name = person["name"].lower()
            if name in known or person["linkedin_url"] in known_urls:
                existing = next((c for c in lead["contacts"] if (c.get("name") or "").lower() == name), None)
                if existing and not existing.get("linkedin_url"):
                    existing["linkedin_url"] = person["linkedin_url"]
                continue
            contact = lead_model.new_contact({**person, "email": "", "email_status": None,
                                              "source": "LinkedIn people search (Apify)"}, lead_model.next_contact_id(lead))
            lead.setdefault("contacts", []).append(contact)
            count += 1
        lead["people_searched_at"] = now_iso()
        store.add_timeline(lead, "people-finder", "people", f"{count} people found on LinkedIn")
        store.save("leads", data)
    store.transact(change, f"people: {lead_id}")
    return count

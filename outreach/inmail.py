"""LinkedIn InMails and the people they go to (Shlok's review, 2026-11-23).

People are found by searching Shlok's own signed-in LinkedIn, at his request, reading search results only
(no profile visits, no messages). They are added here in one transaction with `contact import`. The InMail
is one checked note per job, the same for every person; the site fills in each first name. Shlok sends it
himself. Nothing is ever sent or automated on LinkedIn by this system.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from . import leads as lead_model
from . import messages, store
from .util import now_iso

TEMPLATE = Path(__file__).resolve().parent.parent / "config" / "templates" / "inmail-v1.toml"
ROLE_TYPES = ("hiring_manager", "team_lead", "recruiter", "founder", "employee")
SAMPLE_NAME = "Priya"  # stands in for each person's first name while checking the shared text


def template() -> dict[str, Any]:
    return tomllib.loads(TEMPLATE.read_text(encoding="utf-8"))


def job_link(lead: dict) -> str:
    """The posting's clean public URL: no query string (tracking, sign-in tokens) on LinkedIn."""
    url = lead.get("source_url") or lead.get("apply_url") or ""
    if not url.startswith("https://"):
        return ""
    if "linkedin.com/" in url:
        found = re.search(r"/jobs/view/(?:[^/?#]*-)?(\d+)", url)
        return f"https://www.linkedin.com/jobs/view/{found.group(1)}/" if found else url.split("?")[0]
    return url


def role_name(title: str) -> str:
    """The title as posted, without requisition codes, grades, opening counts or a repeated half."""
    role = re.sub(r"\s*\[[^\]]*\]|\s*\((G\d+|L\d+|\d+ openings?)\)", "", title or "").strip()
    halves = [part.strip() for part in role.split(",")]
    if len(halves) == 2 and halves[0] == halves[1]:
        role = halves[0]
    return role or (title or "").strip()


def company_name(company: str) -> str:
    """'Flipkart (Flipkart Minutes)' -> 'Flipkart'; 'ExxonMobil India Careers' -> 'ExxonMobil India'."""
    name = re.split(r"\s*\(", company or "")[0].strip()
    return re.sub(r"\s+careers$", "", name, flags=re.I) or (company or "").strip()


def unnamed(company: str) -> bool:
    return bool(re.match(r"\s*(undisclosed|unnamed|confidential|stealth)\b", company or "", re.I))


def subject_for(lead: dict) -> str:
    """1-4 words (check_linkedin): the role's main part, with the company when the role alone is one word."""
    company = company_name(lead.get("company", ""))
    parts = [part.strip() for part in re.split(r"\s+[-–|]\s+|\s*\(|-\s+", role_name(lead.get("title", ""))) if part.strip()]
    parts = [part for part in parts if part.lower() != company.lower()] or ["Your open role"]
    short = parts[0]
    if messages.word_count(short) == 1 and not unnamed(company):
        short = f"{short} at {company}"
    return short if 1 <= messages.word_count(short) <= 4 else "Your open role"


def render(lead: dict) -> tuple[dict[str, str], list[str]]:
    """The InMail for one lead and the problems check_linkedin finds (empty means it may be shown)."""
    url = job_link(lead)
    if not url:
        return {}, ["no public link to the posting"]
    company = lead.get("company", "")
    role = role_name(lead.get("title", ""))
    body = template()["body"].replace("{role} role at {company}", f"{role} role" if unnamed(company) else
                                      f"{role} role at {company_name(company)}").replace("{job_url}", url).strip()
    subject = subject_for(lead)
    problems = messages.check_linkedin("inmail", body.replace("{first_name}", SAMPLE_NAME), to_name=SAMPLE_NAME,
                                       company=lead.get("company", ""), subject=subject, job_url=url)
    return {"subject": subject, "body": body, "job_url": url, "template": template()["id"]}, problems


def listed(lead: dict) -> bool:
    return lead.get("type") == "job" and lead.get("stage") == "qualified" and lead.get("open") is not False


def write_all(ids: list[str] | None = None, dry: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {"written": [], "failed": []}

    def change() -> None:
        report.update(written=[], failed=[])
        data = store.load("leads")
        for lead in data["leads"]:
            if (ids and lead["id"] not in ids) or (not ids and not listed(lead)):
                continue
            note, problems = render(lead)
            if problems:
                report["failed"].append({"lead": lead["id"], "company": lead.get("company"), "problems": problems})
                continue
            report["written"].append(lead["id"])
            if not dry:
                lead["inmail"] = {**note, "at": now_iso()}
        if not dry and report["written"]:
            store.save("leads", data)

    if dry:
        change()
    else:
        store.transact(change, f"inmail: {len(ids or [])} leads" if ids else "inmail: listed jobs")
    return {"written": len(report["written"]), "failed": report["failed"], "dry": dry}


def import_people(rows: list[dict]) -> dict[str, Any]:
    """Add people found on LinkedIn to their leads. Skips a person already on the lead (same URL or name)."""
    report: dict[str, Any] = {"added": 0, "skipped": 0, "problems": []}

    def change() -> None:
        report.update(added=0, skipped=0, problems=[])
        data = store.load("leads")
        for row in rows:
            lead = store.find(data["leads"], row.get("lead", ""))
            url = (row.get("linkedin_url") or "").split("?")[0].rstrip("/")
            if not lead or not row.get("name") or not re.match(r"https://(www\.)?linkedin\.com/in/[^/]+$", url):
                report["problems"].append({"row": row.get("name") or row.get("lead"), "why": "no such lead, no name or not a profile URL"})
                continue
            role = row.get("role_type") if row.get("role_type") in ROLE_TYPES else "employee"
            contacts = lead.setdefault("contacts", [])
            if any((c.get("linkedin_url") or "").rstrip("/") == url or c.get("name", "").lower() == row["name"].lower()
                   for c in contacts):
                report["skipped"] += 1
                continue
            contact = lead_model.new_contact({"name": row["name"], "title": row.get("title", ""), "role_type": role,
                                              "linkedin_url": url + "/", "why": row.get("why", "")},
                                             lead_model.next_contact_id(lead))
            contact["found_via"] = "linkedin-search"
            contacts.append(contact)
            store.add_timeline(lead, "people-finder", "contact_added", f"{contact['name']} ({role}, LinkedIn search)")
            report["added"] += 1
        if report["added"]:
            store.save("leads", data)

    store.transact(change, f"people: {len(rows)} from LinkedIn search")
    return report

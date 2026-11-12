"""One-off imports: the earlier tracker batches, the old do-not-email list, LinkedIn connections."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from . import leads as lead_model
from . import store
from .rules import Pay, Verdict, classify_location, parse_experience, parse_pay
from .util import load_config, norm_company, now_iso

LEGACY_DIR = Path.home() / "Claude" / "job_outreach"
LEGACY_FILES = ["tracker_merged_ready.csv", "roles_batch3_final.csv", "roles_batch4_final.csv"]
OLD_PIPELINE = Path.home() / "pipeline"
TIERS = {"1": "1 - Strategy & Ops", "2": "2 - Product / Program / BD", "3": "3 - APM / Analyst"}
TIER_POINTS = {"1": 40, "2": 28, "3": 18}
FIT_POINTS = {"In range": 20, "Likely in range": 14, "Possibly": 10, "Stretch": 6, "Likely below": 2, "Below": 0}


def import_legacy() -> dict[str, int]:
    targeting = load_config("targeting")
    rows: list[dict[str, str]] = []
    for name in LEGACY_FILES:
        path = LEGACY_DIR / name
        if path.exists():
            with open(path, encoding="utf-8-sig", newline="") as handle:
                rows += list(csv.DictReader(handle))
    stats = {"rows": len(rows), "imported": 0, "already_there": 0}

    def change() -> None:
        stats.update(imported=0, already_there=0)
        data = store.load("leads")
        have = {lead.get("legacy_id") for lead in data["leads"]}
        for row in rows:
            legacy = (row.get("ID") or "").strip()
            if not legacy or legacy in have:
                stats["already_there"] += bool(legacy)
                continue
            category = (row.get("Priority Category") or "4")[:1]
            fit = (row.get("Pay Fit") or "Unknown").strip()
            low, high, matched = parse_pay(row.get("Stated Pay") or "")
            pay = Pay(stated=matched or (None if "not stated" in (row.get("Stated Pay") or "").lower() else row.get("Stated Pay")),
                      min_lpa=low, max_lpa=high, basis="stated" if matched else ("estimate" if "estimate" in fit.lower() else "unknown"),
                      source=(row.get("Estimated Pay (with source)") or row.get("Post Source") or "")[:400], fit=fit)
            bucket, loc_points = classify_location(row.get("Location") or "", "", targeting)
            exp_min, exp_max = parse_experience((row.get("Experience Required") or "") + " experience")
            score = TIER_POINTS.get(category, 10) + (loc_points if bucket != "abroad" else 0) + \
                next((points for key, points in FIT_POINTS.items() if fit.startswith(key)), 6) + 10
            verdict = Verdict(True, score=min(score, 100), tier=TIERS.get(category, "4 - Other"),
                              reasons=[f"Imported from tracker {row.get('Batch', '')}: {fit}"],
                              location_bucket=bucket, exp_min=exp_min, exp_max=exp_max, pay=pay,
                              stretch=bool(exp_min and exp_min >= 3))
            apply_link = (row.get("Application Link") or "").strip()
            contacts: list[dict[str, Any]] = []
            if row.get("Post Author"):
                contacts.append({"name": row["Post Author"], "title": row.get("Post Source") or "Post author",
                                 "role_type": "recruiter" if "recruit" in (row.get("Post Source") or "").lower() else "employee",
                                 "linkedin_url": row.get("Post Author LinkedIn") or "",
                                 "why": "Wrote the hiring post"})
            for address in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", row.get("Email in Post") or ""):
                contacts.append({"name": "", "title": "Address given in the post", "role_type": "generic",
                                 "email": address.lower(), "email_status": "published",
                                 "email_source": "stated in the hiring post", "confidence": 95})
            job = {
                "legacy_id": legacy, "source": "linkedin_post", "source_id": legacy,
                "company": row.get("Company"), "title": row.get("Job Profile"), "location": row.get("Location"),
                "work_mode": row.get("Work Mode"), "url": row.get("Post Link"),
                "apply_url": apply_link if apply_link.startswith("http") else "",
                "posted_at": row.get("Posted Date") or None, "description": "",
                "experience_text": row.get("Experience Required") or "",
                "company_note": row.get("Last Funding Round") or "", "contacts": contacts,
            }
            lead = lead_model.new_lead(job, verdict, store.next_id(data["leads"], "L"))
            lead["research"].update(done=True, fit_notes=row.get("Fit Notes") or "",
                                    pay_notes=row.get("Estimated Pay (with source)") or "",
                                    researched_at=now_iso())
            lead["stage"] = "rejected" if fit.startswith("Below") else "qualified"
            if row.get("Contacts (LinkedIn)"):
                lead["notes"].append({"at": now_iso(), "by": "import", "text": "People found earlier: " + row["Contacts (LinkedIn)"]})
            if row.get("Opening Message (copy-paste)"):
                lead["notes"].append({"at": now_iso(), "by": "import",
                                      "text": f"Earlier draft ({row.get('Outreach Channel', 'message')}), not sent:\n"
                                              + row["Opening Message (copy-paste)"]})
            applied = (row.get("Applied? (Shlok fills)") or "").strip()
            if applied and applied.lower() not in ("n", "no"):
                lead["applied_at"] = now_iso()
                lead["apply"]["status"] = "applied"
                lead["apply"]["notes"] = f"Marked in the old tracker: {applied}"
            lead["timeline"] = [{"at": now_iso(), "actor": "import", "event": "imported",
                                 "detail": f"from tracker batch {row.get('Batch', '')} as {legacy}"}]
            data["leads"].append(lead)
            have.add(legacy)
            stats["imported"] += 1
        store.save("leads", data)

    store.transact(change, "import: earlier tracker batches")
    return stats


def import_suppression() -> dict[str, int]:
    """Addresses the old founder pipeline already emailed must never get a new cold email."""
    path = OLD_PIPELINE / "already_mailed.txt"
    addresses = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip().lower()
            if re.fullmatch(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", line):
                addresses.add(line)
    stats = {"found": len(addresses), "added": 0}

    def change() -> None:
        stats["added"] = 0
        data = store.load("suppression")
        for address in addresses:
            if address not in data["emails"]:
                data["emails"][address] = {"reason": "already emailed by the earlier founder pipeline", "at": now_iso()}
                stats["added"] += 1
        store.save("suppression", data)
    store.transact(change, "import: do-not-email list from the earlier pipeline")
    return stats


def import_connections(csv_path: str) -> dict[str, int]:
    """LinkedIn's own export: Settings > Data privacy > Get a copy of your data > Connections."""
    text = Path(csv_path).expanduser().read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.lower().startswith("first name")), None)
    if start is None:
        raise ValueError("this does not look like LinkedIn's Connections.csv (no 'First Name' header row)")
    people = []
    for row in csv.DictReader(lines[start:]):
        name = f"{(row.get('First Name') or '').strip()} {(row.get('Last Name') or '').strip()}".strip()
        if not name or not (row.get("Company") or "").strip():
            continue
        people.append({"name": name, "linkedin_url": (row.get("URL") or "").strip(),
                       "company": row["Company"].strip(), "company_norm": norm_company(row["Company"]),
                       "position": (row.get("Position") or "").strip(),
                       "connected_on": (row.get("Connected On") or "").strip()})

    def change() -> None:
        store.save("connections", {"imported_at": now_iso(), "connections": people})
    store.transact(change, f"import: {len(people)} LinkedIn connections")
    matched = match_connections()
    return {"connections": len(people), **matched}


def match_connections() -> dict[str, int]:
    """Attach to every lead the connections who work at that company, as referral suggestions."""
    stats = {"leads_with_connections": 0, "suggestions_added": 0}

    def change() -> None:
        stats.update(leads_with_connections=0, suggestions_added=0)
        people = store.load("connections")["connections"]
        by_company: dict[str, list[dict]] = {}
        for person in people:
            if len(person.get("company_norm") or "") >= 3:
                by_company.setdefault(person["company_norm"], []).append(person)
        data = store.load("leads")
        for lead in data["leads"]:
            here = by_company.get(norm_company(lead.get("company")), [])
            if not here:
                continue
            stats["leads_with_connections"] += 1
            known = {r.get("linkedin_url") or r.get("name") for r in lead.get("referrals", [])}
            for person in here:
                ident = person.get("linkedin_url") or person["name"]
                if ident in known:
                    continue
                lead.setdefault("referrals", []).append({
                    "name": person["name"], "position": person["position"], "linkedin_url": person["linkedin_url"],
                    "connected_on": person["connected_on"], "status": "suggested", "note": "", "sent_at": None})
                stats["suggestions_added"] += 1
        store.save("leads", data)
    store.transact(change, "referrals: match connections to leads")
    return stats

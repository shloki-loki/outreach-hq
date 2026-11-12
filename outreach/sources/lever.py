"""Lever public postings API: api.lever.co/v0/postings/<slug>?mode=json"""

from __future__ import annotations

from datetime import datetime, timezone

from ..util import HttpError, http_json, strip_html

API = "https://api.lever.co/v0/postings/{slug}?mode=json"


def fetch(targeting: dict, companies: dict) -> tuple[list[dict], list[str]]:
    jobs, errors = [], []
    names = companies.get("names", {})
    for slug in companies.get("lever", {}).get("slugs", []):
        try:
            data = http_json(API.format(slug=slug), timeout=40)
        except (HttpError, ValueError) as exc:
            errors.append(f"lever/{slug}: {exc}")
            continue
        if not isinstance(data, list):
            errors.append(f"lever/{slug}: unexpected response shape")
            continue
        for item in data:
            categories = item.get("categories") or {}
            created = item.get("createdAt")
            posted = datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if created else None
            lists = "\n".join(f"{block.get('text', '')}\n{strip_html(block.get('content'))}"
                              for block in item.get("lists") or [])
            description = "\n".join(filter(None, [item.get("descriptionPlain") or strip_html(item.get("description")),
                                                  lists, item.get("additionalPlain")]))
            salary = item.get("salaryRange") or {}
            pay_text = ""
            if salary.get("min") and salary.get("max"):
                pay_text = f"{salary.get('currency', '')} {salary['min']} - {salary['max']} {salary.get('interval', '')}"
            locations = categories.get("allLocations") or [categories.get("location") or ""]
            jobs.append({
                "source": "lever",
                "source_id": f"{slug}:{item.get('id')}",
                "url": item.get("hostedUrl"),
                "apply_url": item.get("applyUrl") or item.get("hostedUrl"),
                "company": names.get(slug) or slug.replace("-", " ").title(),
                "company_slug": slug,
                "title": (item.get("text") or "").strip(),
                "location": ", ".join(filter(None, locations)),
                "posted_at": posted,
                "description": description,
                "pay_text": pay_text,
            })
    return jobs, errors


def probe(slug: str) -> int | None:
    try:
        data = http_json(API.format(slug=slug), retries=0, timeout=12)
    except (HttpError, ValueError):
        return None
    return len(data) if isinstance(data, list) and data else None

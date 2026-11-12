"""Greenhouse public job-board API: boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true"""

from __future__ import annotations

from ..util import HttpError, http_json, strip_html

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def fetch(targeting: dict, companies: dict) -> tuple[list[dict], list[str]]:
    jobs, errors = [], []
    names = companies.get("names", {})
    for slug in companies.get("greenhouse", {}).get("slugs", []):
        try:
            data = http_json(API.format(slug=slug), timeout=40)
        except (HttpError, ValueError) as exc:
            errors.append(f"greenhouse/{slug}: {exc}")
            continue
        for item in data.get("jobs", []):
            jobs.append({
                "source": "greenhouse",
                "source_id": f"{slug}:{item.get('id')}",
                "url": item.get("absolute_url"),
                "apply_url": item.get("absolute_url"),
                "company": names.get(slug) or slug.replace("-", " ").title(),
                "company_slug": slug,
                "title": (item.get("title") or "").strip(),
                "location": ((item.get("location") or {}).get("name") or "").strip(),
                "posted_at": item.get("first_published") or item.get("updated_at"),
                "description": strip_html(item.get("content")),
                "pay_text": "",
            })
    return jobs, errors


def probe(slug: str) -> int | None:
    try:
        return len(http_json(API.format(slug=slug).replace("?content=true", ""), retries=0, timeout=12).get("jobs", []))
    except (HttpError, ValueError):
        return None

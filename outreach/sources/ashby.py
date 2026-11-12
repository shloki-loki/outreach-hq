"""Ashby public job-board API. It is the one source that often states compensation."""

from __future__ import annotations

from ..util import HttpError, http_json, strip_html

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"


def fetch(targeting: dict, companies: dict) -> tuple[list[dict], list[str]]:
    jobs, errors = [], []
    names = companies.get("names", {})
    for slug in companies.get("ashby", {}).get("slugs", []):
        try:
            data = http_json(API.format(slug=slug), timeout=40)
        except (HttpError, ValueError) as exc:
            errors.append(f"ashby/{slug}: {exc}")
            continue
        for item in data.get("jobs", []):
            if item.get("isListed") is False:
                continue
            places = [item.get("location") or ""]
            places += [extra.get("location", "") for extra in item.get("secondaryLocations") or []]
            if item.get("isRemote"):
                places.append("Remote")
            compensation = item.get("compensation") or {}
            jobs.append({
                "source": "ashby",
                "source_id": f"{slug}:{item.get('id')}",
                "url": item.get("jobUrl"),
                "apply_url": item.get("applyUrl") or item.get("jobUrl"),
                "company": names.get(slug) or slug.replace("-", " ").title(),
                "company_slug": slug,
                "title": (item.get("title") or "").strip(),
                "location": ", ".join(dict.fromkeys(filter(None, places))),
                "posted_at": item.get("publishedAt"),
                "description": item.get("descriptionPlain") or strip_html(item.get("descriptionHtml")),
                "pay_text": compensation.get("compensationTierSummary") or compensation.get("scrapeableCompensationSalarySummary") or "",
            })
    return jobs, errors


def probe(slug: str) -> int | None:
    try:
        return len(http_json(API.format(slug=slug), retries=0, timeout=12).get("jobs", []))
    except (HttpError, ValueError):
        return None

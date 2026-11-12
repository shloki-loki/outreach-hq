"""Instahyre's public job search (the listing a logged-out visitor sees)."""

from __future__ import annotations

import time
import urllib.parse

from ..util import HttpError, http_json

API = "https://www.instahyre.com/api/v1/job_search?"


def fetch(targeting: dict, companies: dict) -> tuple[list[dict], list[str]]:
    cfg = targeting["instahyre"]
    jobs: dict[str, dict] = {}
    errors: list[str] = []
    for query in cfg["queries"]:
        for location in cfg["locations"]:
            params = urllib.parse.urlencode({"company_size": 0, "isLandingPage": "true", "job_type": 0,
                                             "limit": 30, "offset": 0, "location": location, "skills": query})
            try:
                data = http_json(API + params)
            except (HttpError, ValueError) as exc:
                errors.append(f"instahyre '{query}' / {location}: {exc}")
                continue
            for item in data.get("objects", []):
                employer = item.get("employer") or {}
                jobs.setdefault(str(item.get("id")), {
                    "source": "instahyre",
                    "source_id": str(item.get("id")),
                    "url": item.get("public_url"),
                    "apply_url": item.get("public_url"),
                    "company": (employer.get("company_name") or "").strip(),
                    "title": (item.get("title") or "").strip(),
                    "location": item.get("locations") or "",
                    "posted_at": None,
                    "description": " ".join(filter(None, [employer.get("company_tagline"),
                                                           ", ".join(item.get("keywords") or [])])),
                    "pay_text": "",
                })
            time.sleep(0.8)
    return list(jobs.values()), errors

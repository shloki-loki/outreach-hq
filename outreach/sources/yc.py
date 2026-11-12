"""Y Combinator, all public and login-free.

- yc-oss publishes YC's "currently hiring" company list as JSON, refreshed daily.
- Each company page on ycombinator.com embeds its jobs and founders (with LinkedIn URLs) as JSON.
Founders come back as contacts, so a YC job lead arrives with the people to write to.
"""

from __future__ import annotations

import html
import json
import re
import time

from ..util import HttpError, http_get, http_json, strip_html, word_match

HIRING = "https://yc-oss.github.io/api/companies/hiring.json"
PAGE = "https://www.ycombinator.com/companies/{slug}"


def parse_page(page: str) -> dict:
    found = re.search(r'data-page="([^"]*)"', page)
    if not found:
        raise ValueError("no data-page JSON on the page; YC may have changed its site")
    return json.loads(html.unescape(found.group(1)))


def fetch(targeting: dict, companies: dict, skip_slugs: set[str] | None = None) -> tuple[list[dict], list[str]]:
    cfg = targeting["yc"]
    errors: list[str] = []
    try:
        hiring = http_json(HIRING, timeout=60)
    except (HttpError, ValueError) as exc:
        return [], [f"yc hiring list: {exc}"]
    wanted = {region.lower() for region in cfg["regions"]}
    picked = []
    for company in hiring:
        if company.get("status") != "Active":
            continue
        regions = {region.lower() for region in company.get("regions") or []}
        places = (company.get("all_locations") or "").lower()
        if not (regions & wanted) and "india" not in places:
            continue
        if (company.get("team_size") or 0) > cfg["max_team_size"]:
            continue
        if any(word_match(bad, company.get("name") or "") for bad in targeting["companies"]["exclude"]):
            continue
        picked.append(company)
    # India-based companies first, then by most recently launched.
    picked.sort(key=lambda c: ("india" not in (c.get("all_locations") or "").lower(), -(c.get("launched_at") or 0)))
    skip = skip_slugs or set()
    picked = [company for company in picked if company.get("slug") not in skip][: cfg["companies_per_run"]]

    jobs = []
    for company in picked:
        slug = company["slug"]
        try:
            props = parse_page(http_get(PAGE.format(slug=slug)).decode("utf-8", "replace"))["props"]
        except (HttpError, ValueError, KeyError) as exc:
            errors.append(f"yc/{slug}: {exc}")
            continue
        detail = props.get("company") or {}
        founders = [{
            "name": founder.get("full_name"), "title": founder.get("title") or "Founder",
            "role_type": "founder", "linkedin_url": founder.get("linkedin_url") or "",
        } for founder in detail.get("founders") or [] if founder.get("full_name") and founder.get("is_active", True)]
        for posting in props.get("jobPostings") or []:
            jobs.append({
                "source": "yc",
                "source_id": f"{slug}:{posting.get('id')}",
                "url": "https://www.ycombinator.com" + (posting.get("url") or f"/companies/{slug}"),
                "apply_url": f"https://www.workatastartup.com/jobs/{posting.get('id')}",
                "company": detail.get("name") or company.get("name"),
                "company_slug": slug,
                "company_url": detail.get("website") or company.get("website") or "",
                "company_linkedin": detail.get("linkedin_url") or "",
                "company_note": f"YC {company.get('batch') or ''} · team of {company.get('team_size') or '?'} · {company.get('one_liner') or ''}".strip(),
                "title": (posting.get("title") or "").strip(),
                "location": posting.get("location") or detail.get("location") or "",
                "posted_at": posting.get("createdAt") or None,
                "description": strip_html(posting.get("description") or "") or (company.get("long_description") or ""),
                "experience_text": f"{posting.get('minExperience') or ''} experience",
                "pay_text": posting.get("salaryRange") or "",
                "contacts": founders,
            })
        # An India-based YC company that is hiring but lists no named role is still worth a note to
        # the founders: a "company" lead, scored lower than a real posting.
        in_india = "india" in f"{detail.get('location') or ''} {company.get('all_locations') or ''}".lower()
        if in_india and founders:
            jobs.append({
                "source": "yc", "type": "company", "source_id": f"{slug}:company",
                "url": f"https://www.ycombinator.com/companies/{slug}", "apply_url": "",
                "company": detail.get("name") or company.get("name"), "company_slug": slug,
                "company_url": detail.get("website") or company.get("website") or "",
                "company_linkedin": detail.get("linkedin_url") or "",
                "company_note": f"YC {company.get('batch') or ''} · team of {company.get('team_size') or '?'} · {company.get('one_liner') or ''}".strip(),
                "title": "Founder's Office (speculative note to founders)",
                "location": detail.get("location") or company.get("all_locations") or "India",
                "posted_at": None, "description": company.get("long_description") or "",
                "pay_text": "", "contacts": founders,
            })
        time.sleep(0.6)
    return jobs, errors

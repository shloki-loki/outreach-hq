"""LinkedIn's public, logged-out job search (the pages a visitor sees without an account).

No account or cookie is used, so there is nothing of Shlok's to restrict. LinkedIn rate-limits
these pages hard (HTTP 429), so searches are paced and descriptions are read only for jobs
whose title already passes the rules.
"""

from __future__ import annotations

import html
import random
import re
import time
import urllib.parse

from ..util import HttpError, http_get, strip_html

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"

_CARD = re.compile(r"<li>(.*?)</li>", re.S)


def _text(pattern: str, block: str) -> str:
    match = re.search(pattern, block, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip() if match else ""


def parse_cards(page: str) -> list[dict]:
    jobs = []
    for block in _CARD.findall(page):
        ident = re.search(r"urn:li:jobPosting:(\d+)", block)
        title = _text(r'base-search-card__title[^>]*>(.*?)</h3>', block)
        if not ident or not title:
            continue
        link = re.search(r'href="(https://[a-z.]*linkedin\.com/jobs/view/[^"?]+)', block)
        company_link = re.search(r'href="(https://[a-z.]*linkedin\.com/company/[^"?]+)', block)
        posted = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        jobs.append({
            "source": "linkedin",
            "source_id": ident.group(1),
            "url": link.group(1) if link else f"https://www.linkedin.com/jobs/view/{ident.group(1)}",
            "apply_url": link.group(1) if link else f"https://www.linkedin.com/jobs/view/{ident.group(1)}",
            "company": _text(r'base-search-card__subtitle[^>]*>(.*?)</h4>', block),
            "company_linkedin": company_link.group(1) if company_link else "",
            "title": title,
            "location": _text(r'job-search-card__location[^>]*>(.*?)</span>', block),
            "posted_at": posted.group(1) if posted else None,
            "description": "",
            "pay_text": _text(r'job-search-card__salary-info[^>]*>(.*?)</span>', block),
        })
    return jobs


def fetch(targeting: dict, companies: dict) -> tuple[list[dict], list[str]]:
    cfg = targeting["linkedin"]
    jobs: dict[str, dict] = {}
    errors: list[str] = []
    blocked = 0
    for keyword in cfg["keywords"]:
        for location in cfg["locations"]:
            for page in range(cfg["pages_per_search"]):
                query = urllib.parse.urlencode({"keywords": keyword, "location": location,
                                                "f_TPR": cfg["posted_within"], "sortBy": "DD", "start": page * 10})
                try:
                    body = http_get(SEARCH + query, retries=2, backoff=8).decode("utf-8", "replace")
                except HttpError as exc:
                    blocked += 1
                    errors.append(f"linkedin search '{keyword}' / {location}: {exc}")
                    break
                cards = parse_cards(body)
                for card in cards:
                    jobs.setdefault(card["source_id"], card)
                time.sleep(random.uniform(1.5, 3.0))
                if len(cards) < 10:
                    break
            if blocked >= 4:  # being throttled: stop politely and keep what we have
                errors.append("linkedin: stopped early after repeated rate limits")
                return list(jobs.values()), errors
    return list(jobs.values()), errors


def fetch_detail(job_id: str) -> dict:
    """Read one posting's description, criteria and offsite apply link. Raises HttpError on 429."""
    page = http_get(DETAIL.format(id=job_id), retries=2, backoff=10).decode("utf-8", "replace")
    description = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', page, re.S)
    criteria = [re.sub(r"\s+", " ", strip_html(item)) for item in
                re.findall(r'description__job-criteria-item">(.*?)</li>', page, re.S)]
    apply = re.search(r'<code id="applyUrl"[^>]*><!--"(.*?)"-->', page, re.S)
    apply_url = ""
    if apply:
        target = urllib.parse.parse_qs(urllib.parse.urlparse(html.unescape(apply.group(1))).query).get("url")
        apply_url = target[0] if target else html.unescape(apply.group(1))
    salary = re.search(r'compensation__salary[^>]*>(.*?)<', page, re.S)
    return {
        "description": strip_html(description.group(1)) if description else "",
        "criteria": criteria,
        "apply_url": apply_url,
        "pay_text": strip_html(salary.group(1)) if salary else "",
    }

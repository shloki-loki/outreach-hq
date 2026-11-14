"""Naukri, Wellfound and Hiring Cafe, read through Apify actors (the sites block plain requests).

Needs APIFY_TOKEN (a GitHub secret). Without it these sources are skipped quietly, so the free sources
keep working. Every call is capped twice:
  - per call, with Apify's own `maxTotalChargeUsd` (the actor stops billing at that amount), and
  - per month, with [apify] monthly_cap_usd in config/settings.toml, checked against Apify's real usage
    figure for the account before each call (and against our own ledger when that figure is unavailable).
Each source also runs at most once every `every_days` days (config/targeting.toml [apify.*]).

Actors were chosen on 2026-11-14 by usage and a test run: valig/naukri-jobs-scraper (13k users,
$0.0004 a job), clearpath/wellfound-api-ppe (1.1k users, $0.003 a job with the full description),
memo23/apify-hiring-cafe-scraper (rated 5.0, $0.00125 a job with the full description).
"""

from __future__ import annotations

import json
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from .. import store
from ..util import HttpError, http_get, load_config, strip_html, today

API = "https://api.apify.com/v2"


class BudgetSpent(Exception):
    pass


def token() -> str | None:
    return os.environ.get("APIFY_TOKEN") or None


def month_usage_usd() -> float | None:
    """What Apify says this account has used this billing month, or None if it cannot be read."""
    try:
        data = json.loads(http_get(f"{API}/users/me/limits", headers={"Authorization": f"Bearer {token()}"},
                                   retries=1, timeout=20)).get("data", {})
        value = (data.get("current") or {}).get("monthlyUsageUsd")
        return float(value) if value is not None else None
    except (HttpError, ValueError):
        return None


def ledger_usd() -> float:
    return float(store.load("quotas")["usage"].get(f"apify_usd:{today()[:7]}", 0))


def _record(spend: float) -> None:
    def change() -> None:
        quotas = store.load("quotas")
        bucket = f"apify_usd:{today()[:7]}"
        quotas["usage"][bucket] = round(float(quotas["usage"].get(bucket, 0)) + spend, 4)
        store.save("quotas", quotas)
    store.transact(change, "quotas: apify spend")


def run_actor(actor: str, payload: dict, max_usd: float, timeout: int = 280) -> list[dict]:
    """Run an actor synchronously and return its dataset. Raises BudgetSpent before going over the cap."""
    if not token():
        raise BudgetSpent("APIFY_TOKEN is not set")
    cap = float(load_config("settings").get("apify", {}).get("monthly_cap_usd", 3.5))
    used = month_usage_usd()
    used = ledger_usd() if used is None else used
    if used + max_usd > cap:
        raise BudgetSpent(f"Apify spend this month is ${used:.2f}; one more run (up to ${max_usd:.2f}) "
                          f"would pass the ${cap:.2f} cap")
    query = urllib.parse.urlencode({"maxTotalChargeUsd": max_usd, "timeout": timeout, "format": "json", "clean": "true"})
    url = f"{API}/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items?{query}"
    try:
        body = http_get(url, data=json.dumps(payload).encode(), retries=0, timeout=timeout + 30,
                        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    finally:
        _record(max_usd)  # the ledger counts the cap, an upper bound on what the run can cost
    items = json.loads(body or b"[]")
    return items if isinstance(items, list) else []


def due(name: str, every_days: int) -> bool:
    last = store.load("seen")["keys"].get(f"apify:{name}", {}).get("at", "")
    if not last:
        return True
    return (datetime.fromisoformat(today()) - datetime.fromisoformat(last)).days >= every_days


def mark_ran(name: str) -> None:
    def change() -> None:
        seen = store.load("seen")
        seen["keys"][f"apify:{name}"] = {"v": "ran", "at": today()}
        store.save("seen", seen)
    store.transact(change, f"scout: {name} ran")


def _date_ms(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value) / (1000 if float(value) > 1e11 else 1), timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


# ---- per-site mapping ----------------------------------------------------------------------

def naukri_jobs(items: list[dict]) -> list[dict]:
    jobs = []
    for item in items:
        if item.get("consultant"):  # posted by a recruitment agency; the employer is hidden
            continue
        company = item.get("company") or {}
        rating = (item.get("ambitionBox") or {}).get("companyInfo") or {}
        salary = item.get("salary") or {}
        jobs.append({
            "source": "naukri", "source_id": str(item.get("id")), "url": item.get("url"),
            "apply_url": item.get("companyApplyJob") or item.get("url"),
            "company": (company.get("name") or "").strip(), "title": (item.get("title") or "").strip(),
            "location": ", ".join(loc.get("label", "") for loc in item.get("locations") or []),
            "posted_at": _date_ms(item.get("createdDate")),
            "description": strip_html((item.get("description") or {}).get("full") or ""),
            "pay_text": salary.get("label") or "", "experience_text": (item.get("experience") or {}).get("text") or "",
            "company_url": company.get("websiteUrl") or "",
            "company_note": (f"AmbitionBox {rating.get('AggregateRating')} ({rating.get('ReviewsCount')} reviews, via Naukri)"
                             if rating.get("AggregateRating") else ""),
        })
    return jobs


def wellfound_jobs(items: list[dict]) -> list[dict]:
    jobs = []
    for item in items:
        low, high = item.get("years_experience_min"), item.get("years_experience_max")
        jobs.append({
            "source": "wellfound", "source_id": str(item.get("id")), "url": item.get("url"), "apply_url": item.get("url"),
            "company": (item.get("company_name") or "").strip(), "title": (item.get("title") or "").strip(),
            "location": ", ".join(item.get("location_names") or []) + (" (remote)" if item.get("remote") else ""),
            "posted_at": _date_ms(item.get("live_start_at")),
            "description": strip_html(item.get("description") or item.get("description_snippet") or ""),
            "pay_text": item.get("compensation") or "",
            "experience_text": (f"{low}-{high} years" if low is not None and high else f"{low}+ years" if low is not None else ""),
            "company_url": f"https://wellfound.com/company/{item.get('company_slug')}" if item.get("company_slug") else "",
            "company_note": (item.get("company_high_concept") or "")[:160],
        })
    return jobs


def hiringcafe_jobs(items: list[dict]) -> list[dict]:
    jobs = []
    for item in items:
        if item.get("is_expired"):
            continue
        info, data = item.get("job_information") or {}, item.get("v5_processed_job_data") or {}
        low, high = data.get("yearly_min_compensation"), data.get("yearly_max_compensation")
        currency = data.get("listed_compensation_currency") or ""
        pay = ""
        if currency == "INR" and (low or high):
            pay = f"Rs {round((low or high) / 1e5, 1)}-{round((high or low) / 1e5, 1)} LPA"
        years = data.get("min_industry_and_role_yoe")
        website = data.get("company_website") or ""
        jobs.append({
            "source": "hiringcafe", "source_id": str(item.get("objectID") or item.get("id")),
            "url": item.get("apply_url"), "apply_url": item.get("apply_url"),
            "company": (data.get("company_name") or "").strip(), "title": (info.get("title") or "").strip(),
            "location": data.get("formatted_workplace_location") or "",
            "posted_at": (data.get("estimated_publish_date") or "")[:10] or None,
            "description": strip_html(info.get("description") or info.get("descriptionText") or ""),
            "pay_text": pay, "experience_text": f"{years}+ years" if years is not None else "",
            "company_url": f"https://{website}" if website and not website.startswith("http") else website,
            "company_note": (data.get("company_tagline") or "")[:160],
        })
    return jobs


SITES = {
    "naukri": ("valig/naukri-jobs-scraper", naukri_jobs),
    "wellfound": ("clearpath/wellfound-api-ppe", wellfound_jobs),
    "hiringcafe": ("memo23/apify-hiring-cafe-scraper", hiringcafe_jobs),
}


def inputs(name: str, cfg: dict) -> list[dict]:
    if name == "naukri":
        return [{"keywords": keyword, "location": location, "sort": "f", "jobAge": str(cfg.get("job_age_days", 7)),
                 "experience": cfg.get("experience_years", 1), "jobPostType": ["1"], "limit": cfg.get("per_search", 30)}
                for keyword in cfg["keywords"] for location in cfg["locations"]]
    if name == "wellfound":
        return [{"urls": cfg["urls"], "pageLimit": 1, "sortBy": "LAST_POSTED"}]
    return [{"keyword": keyword, "location": cfg.get("location", "India"), "dateFetchedPastNDays": cfg.get("days", 7),
             "sortBy": "date", "maxItems": cfg.get("per_search", 25), "maxConcurrency": 5, "maxRequestRetries": 5}
            for keyword in cfg["keywords"]]


def fetch_site(name: str, targeting: dict) -> tuple[list[dict], list[str]]:
    cfg = targeting.get("apify", {}).get(name)
    if not cfg or not cfg.get("enabled", True):
        return [], []
    if not token():
        return [], []  # not set up yet: skip quietly (scout does not file an issue for this)
    if not due(name, int(cfg.get("every_days", 1))):
        return [], []
    actor, mapper = SITES[name]
    jobs: list[dict] = []
    errors: list[str] = []
    for payload in inputs(name, cfg):
        try:
            jobs += mapper(run_actor(actor, payload, float(cfg.get("max_usd_per_call", 0.1))))
        except BudgetSpent as exc:
            errors.append(f"{name}: {exc}")
            break
        except (HttpError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    if jobs or not errors:
        mark_ran(name)
    unique = {job["source_id"]: job for job in jobs if job.get("title") and job.get("company")}
    return list(unique.values()), errors


class _Site:
    """Adapter so each site plugs into sources.ALL like the free sources."""

    def __init__(self, name: str) -> None:
        self.name = name

    def fetch(self, targeting: dict, companies: dict) -> tuple[list[dict], list[str]]:
        return fetch_site(self.name, targeting)


naukri, wellfound, hiringcafe = _Site("naukri"), _Site("wellfound"), _Site("hiringcafe")

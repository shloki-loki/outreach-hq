"""Lead generation, deterministic half: read every free source, apply the rules, store what passes.

The lead-scout agent then researches the stored leads (fit, pay evidence, people, emails).
"""

from __future__ import annotations

import random
import time
from typing import Any

from . import leads as lead_model
from . import store
from .rules import judge
from .sources import ALL, linkedin
from .util import HttpError, load_config, today


def gather(only: list[str] | None = None) -> tuple[list[dict], dict[str, Any]]:
    """Fetch raw jobs from every source. Network only; touches no stored data."""
    targeting, companies = load_config("targeting"), load_config("companies")
    seen = store.load("seen")["keys"]
    jobs: list[dict] = []
    report: dict[str, Any] = {"sources": {}, "errors": [], "boards_ok": []}
    for name, module in ALL.items():
        if only and name not in only:
            continue
        try:
            if name == "yc":
                recent = {key[3:] for key, value in seen.items()
                          if key.startswith("yc:") and value.get("at", "") >= _days_ago(5)}
                found, errors = module.fetch(targeting, companies, skip_slugs=recent)
                report["yc_slugs"] = sorted({job["company_slug"] for job in found})
            else:
                found, errors = module.fetch(targeting, companies)
        except Exception as exc:  # one broken source must not stop the others
            found, errors = [], [f"{name}: crashed: {exc!r}"]
        report["sources"][name] = len(found)
        report["errors"] += errors
        if name in ("greenhouse", "lever", "ashby"):
            failed = {error.split(":")[0].split("/")[1] for error in errors if "/" in error.split(":")[0]}
            for slug in companies.get(name, {}).get("slugs", []):
                if slug not in failed:
                    report["boards_ok"].append(f"{name}:{slug}")
        jobs += found
    return jobs, report


def _days_ago(days: int) -> str:
    from datetime import timedelta
    from .util import now
    return (now() - timedelta(days=days)).strftime("%Y-%m-%d")


def shortlist(jobs: list[dict]) -> tuple[list[tuple[dict, Any]], dict[str, int]]:
    """Apply the rules. LinkedIn jobs that pass on title get their description read first."""
    targeting = load_config("targeting")
    seen = store.load("seen")["keys"]
    known_ids = {(lead.get("source"), lead.get("source_id")) for lead in store.load("leads")["leads"]}
    kept: list[tuple[dict, Any]] = []
    reasons: dict[str, int] = {}
    detail_budget = targeting["linkedin"]["detail_fetches_per_run"]
    throttled = False

    for job in jobs:
        verdict = judge(job, targeting)
        if verdict.keep and job["source"] == "linkedin" and not job.get("description"):
            seen_key = f"li:{job['source_id']}"
            if seen_key in seen and seen[seen_key].get("v", "").startswith("rejected"):
                reasons["already rejected on description"] = reasons.get("already rejected on description", 0) + 1
                continue
            if (job["source"], job["source_id"]) not in known_ids and detail_budget > 0 and not throttled:
                detail_budget -= 1
                try:
                    detail = linkedin.fetch_detail(job["source_id"])
                    job["description"] = detail["description"]
                    job["experience_text"] = " ".join(detail["criteria"])
                    job["pay_text"] = job.get("pay_text") or detail["pay_text"]
                    if detail["apply_url"]:
                        job["apply_url"] = detail["apply_url"]
                    verdict = judge(job, targeting)
                    job["_detail_verdict"] = "kept" if verdict.keep else f"rejected: {verdict.reject_reason}"
                except HttpError as exc:
                    throttled = exc.status == 429
                time.sleep(random.uniform(2.0, 4.0))
        if verdict.keep:
            kept.append((job, verdict))
        else:
            reason = (verdict.reject_reason or "rejected").split("(")[0].strip()
            reasons[reason] = reasons.get(reason, 0) + 1
    return kept, reasons


def store_leads(kept: list[tuple[dict, Any]], report: dict[str, Any]) -> dict[str, int]:
    """Merge the shortlist into the stored leads. Safe to run again on fresh data."""
    stats = {"new": 0, "updated": 0, "closed": 0}

    def change() -> None:
        stats.update(new=0, updated=0, closed=0)
        data = store.load("leads")
        seen = store.load("seen")
        by_key = {lead["key"]: lead for lead in data["leads"]}
        by_source = {(lead.get("source"), lead.get("source_id")): lead for lead in data["leads"]}
        live_ids = set(report.get("live_ids") or [])
        for job, verdict in kept:
            live_ids.add((job["source"], job["source_id"]))
            key = lead_model.lead_key(job.get("company", ""), job.get("title", ""), verdict.location_bucket)
            lead = by_source.get((job["source"], job["source_id"])) or by_key.get(key)
            if lead:
                if lead_model.merge_job(lead, job, verdict):
                    stats["updated"] += 1
                continue
            lead = lead_model.new_lead(job, verdict, store.next_id(data["leads"], "L"))
            data["leads"].append(lead)
            by_key[lead["key"]] = lead
            by_source[(lead["source"], lead["source_id"])] = lead
            stats["new"] += 1
            if job.get("_detail_verdict"):
                seen["keys"][f"li:{job['source_id']}"] = {"v": job["_detail_verdict"], "at": today()}
        # A job that vanished from a board we read successfully has been taken down.
        boards_ok = set(report.get("boards_ok", []))
        for lead in data["leads"]:
            board = f"{lead.get('source')}:{str(lead.get('source_id', '')).split(':')[0]}"
            if board in boards_ok and lead.get("open") and (lead["source"], lead["source_id"]) not in live_ids \
                    and lead.get("last_seen") != today():
                lead["open"] = False
                store.add_timeline(lead, "lead-scout", "posting_closed", "no longer on the company's job board")
                stats["closed"] += 1
        for slug in report.get("yc_slugs", []):
            seen["keys"][f"yc:{slug}"] = {"v": "read", "at": today()}
        store.save("leads", data)
        store.save("seen", seen)

    store.transact(change, f"scout: {today()}")
    return stats


def record_rejections(jobs: list[dict]) -> None:
    """Remember LinkedIn jobs rejected after their description was read, so they are not re-read."""
    rejected = {f"li:{job['source_id']}": {"v": job["_detail_verdict"], "at": today()}
                for job in jobs if job.get("_detail_verdict", "").startswith("rejected")}
    if not rejected:
        return

    def change() -> None:
        seen = store.load("seen")
        seen["keys"].update(rejected)
        store.save("seen", seen)
    store.transact(change, "scout: remember rejected postings")


def run(only: list[str] | None = None, dry: bool = False) -> dict[str, Any]:
    store.sync()
    jobs, report = gather(only)
    report["live_ids"] = {(job["source"], job["source_id"]) for job in jobs}
    kept, reasons = shortlist(jobs)
    summary: dict[str, Any] = {"fetched": len(jobs), "passed_rules": len(kept), "by_source": report["sources"],
                               "rejected_for": dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:8]),
                               "errors": report["errors"]}
    if dry:
        summary["sample"] = [f"{v.score} | {j['company']} | {j['title']} | {j['location']}" for j, v in
                             sorted(kept, key=lambda pair: -pair[1].score)[:40]]
        return summary
    summary.update(store_leads(kept, report))
    record_rejections(jobs)
    ok = bool(jobs) or not report["errors"]
    store.log_run("lead-scout/scrape", ok,
                  f"{summary['fetched']} jobs read, {summary['passed_rules']} passed rules, {summary['new']} new leads",
                  {k: summary[k] for k in ("fetched", "passed_rules", "new", "updated", "closed", "by_source")})
    for name, count in report["sources"].items():
        if count == 0:
            store.open_issue("lead-scout", f"Source '{name}' returned no jobs",
                             "; ".join(e for e in report["errors"] if e.startswith(name))[:600] or "No error, just empty.",
                             key=f"source-empty:{name}")
    return summary

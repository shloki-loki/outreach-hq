"""Daily live check: open every lead's posting and move the ones that are gone to the Bin.

A lead is binned only on a clear signal: the board's API says the job no longer exists (HTTP 404/410),
or the page itself says it has stopped taking applications. A timeout, a rate limit or a login wall is
"could not check", never "closed". Binned leads keep everything they had; `lead set <id> --reopen`
brings one back.

Leads already in a conversation (a reply, an interview, an offer) are never binned: a closed posting
does not end a conversation that has started.
"""

from __future__ import annotations

import random
import re
import time
from typing import Any

from . import store
from .util import HttpError, http_get, http_json, now_iso, today

# Only phrases that announce a closure. "Applications accepted until the position is filled" is an open job.
CLOSED_TEXT = re.compile(
    r"no longer accepting applications|closed-job__flavor--closed|is no longer accepting responses|"
    r"this (job|position|role|opening|posting|vacancy) (has been (closed|filled|removed)|has expired|is (now )?closed|"
    r"is no longer (available|active|open|accepting))|job (posting )?has expired|job not found|"
    r"we are no longer hiring for this",
    re.I)


class Unknown(Exception):
    """The posting could not be checked this time (network, rate limit, login wall)."""


def _page_closed(url: str) -> tuple[bool, str]:
    if not re.match(r"https?://\S+$", url.strip()):
        raise Unknown(f"apply link is not a usable URL: {url[:80]}")
    try:
        page = http_get(url, retries=1, backoff=6, timeout=25).decode("utf-8", "replace")
    except HttpError as exc:
        if exc.status in (404, 410):
            return True, f"the posting page no longer exists (HTTP {exc.status})"
        raise Unknown(str(exc)) from None
    match = CLOSED_TEXT.search(page)
    if not match:
        return False, ""
    said = match.group(0)
    if "closed-job" in said or said.lower().startswith("no longer accepting"):
        said = "No longer accepting applications"
    return True, f"the posting says \"{said}\""


def probe(lead: dict) -> tuple[bool, str]:
    """(closed, why). Raises Unknown when the posting cannot be checked."""
    source, ident = lead.get("source"), str(lead.get("source_id") or "")
    slug, _, job = ident.partition(":")
    try:
        if source == "linkedin":
            return _page_closed(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{ident}")
        if source == "greenhouse" and job:
            http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job}", retries=1, timeout=20)
            return False, ""
        if source == "lever" and job:
            http_json(f"https://api.lever.co/v0/postings/{slug}/{job}", retries=1, timeout=20)
            return False, ""
        if source == "ashby" and job:
            board = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", retries=1, timeout=30)
            ids = {item.get("id") for item in board.get("jobs", [])}
            return (False, "") if job in ids else (True, "no longer on the company's Ashby job board")
    except HttpError as exc:
        if exc.status in (404, 410):
            return True, f"the job board says the posting no longer exists (HTTP {exc.status})"
        raise Unknown(str(exc)) from None
    url = lead.get("source_url") or lead.get("apply_url")
    if source == "linkedin_post":
        # The post itself needs a LinkedIn login. Check where it sends people to apply, if anywhere else.
        url = lead.get("apply_url") or ""
        job_id = re.search(r"linkedin\.com/jobs/view/(?:[^/?]*-)?(\d{8,})", url)
        if job_id:
            return _page_closed(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id.group(1)}")
        if not url or "linkedin.com/" in url:
            raise Unknown("a LinkedIn post with no outside apply link; it needs a signed-in look")
    if not url or lead.get("type") == "company":
        raise Unknown("a company with no posting; nothing to check")
    return _page_closed(url)


def in_conversation(lead: dict) -> bool:
    return bool(lead.get("replied_at")) or lead.get("outcome") in ("interview", "offer")


def due(lead: dict) -> bool:
    if lead.get("open") is False or lead.get("stage") == "skipped" or in_conversation(lead) or lead.get("source") == "manual":
        return False
    if lead.get("outcome") in ("rejected", "closed"):
        return False
    return (lead.get("live_check") or {}).get("at", "")[:10] != today()


def run(limit: int | None = None, dry: bool = False, only: str | None = None) -> dict[str, Any]:
    store.sync()
    every = store.load("leads")["leads"]
    # A named lead is checked even if it was already checked today.
    leads = [lead for lead in every if lead["id"] == only] if only else [lead for lead in every if due(lead)]
    # Leads Shlok might act on first, then the rest.
    leads.sort(key=lambda lead: (lead.get("stage") != "qualified", -(lead.get("score") or {}).get("total", 0)))
    if limit:
        leads = leads[:limit]
    results: dict[str, dict] = {}
    stats = {"checked": 0, "live": 0, "binned": 0, "unknown": 0}
    linkedin_blocked = 0
    for lead in leads:
        if lead.get("source") == "linkedin" and linkedin_blocked >= 3:
            results[lead["id"]] = {"state": "unknown", "why": "LinkedIn rate limit; skipped this run"}
            stats["unknown"] += 1
            continue
        try:
            closed, why = probe(lead)
            results[lead["id"]] = {"state": "closed" if closed else "live", "why": why}
            stats["binned" if closed else "live"] += 1
        except Exception as exc:  # anything unexpected is "could not check", never "closed"
            results[lead["id"]] = {"state": "unknown", "why": str(exc)[:200]}
            stats["unknown"] += 1
            if lead.get("source") == "linkedin" and ("429" in str(exc) or "999" in str(exc)):
                linkedin_blocked += 1
        stats["checked"] += 1
        if lead.get("source") == "linkedin":
            time.sleep(random.uniform(1.5, 3.0))
    if dry:
        return {**stats, "results": results}

    def change() -> None:
        data = store.load("leads")
        for lead in data["leads"]:
            result = results.get(lead["id"])
            if not result:
                continue
            lead["live_check"] = {"at": now_iso(), "state": result["state"], "why": result["why"]}
            if result["state"] == "closed" and not in_conversation(lead):
                lead["open"] = False
                lead["bin"] = {"at": now_iso(), "reason": result["why"], "by": "live-check"}
                store.add_timeline(lead, "live-check", "posting_closed", f"moved to the Bin: {result['why']}")
            elif result["state"] == "live" and lead.get("stage") == "qualified":
                lead["verified_at"] = now_iso()
        store.save("leads", data)
    store.transact(change, f"live check: {today()}")
    store.log_run("live-check", True, f"{stats['checked']} postings checked: {stats['live']} live, "
                  f"{stats['binned']} moved to the Bin, {stats['unknown']} could not be checked", stats)
    return {**stats, "binned_ids": [k for k, v in results.items() if v["state"] == "closed"]}

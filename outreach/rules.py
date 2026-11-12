"""Deterministic checks and scoring that run before any research.

They decide what is worth the lead-scout agent's time: right kind of role, right seniority, in India
or remote, and not visibly below the pay floor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .util import parse_iso, now, word_match

# ---- titles -------------------------------------------------------------------------------


def classify_title(title: str, targeting: dict) -> tuple[str | None, int, bool, str | None]:
    """Returns (tier name, tier points, is_stretch, reject_reason)."""
    for pattern in targeting["titles"]["exclude"]:
        if re.search(pattern, title, re.I):
            return None, 0, False, f"title excluded ({pattern})"
    for tier in targeting["tiers"]:
        if any(re.search(pattern, title, re.I) for pattern in tier["patterns"]):
            stretch = any(re.search(pattern, title, re.I) for pattern in targeting["titles"]["stretch"])
            return tier["name"], tier["points"], stretch, None
    return None, 0, False, "title matches no target role"


# ---- location -----------------------------------------------------------------------------

def classify_location(location: str, description: str, targeting: dict) -> tuple[str, int]:
    """Returns (bucket, points). Buckets: bengaluru, remote, india, abroad, unknown."""
    cfg = targeting["location"]
    place = (location or "").lower()
    if any(word in place for word in cfg["preferred"]):
        return "bengaluru", 20
    is_remote = any(word in place for word in cfg["remote_words"])
    in_india = any(re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", place) for word in cfg["india_words"])
    if is_remote and (in_india or not _names_other_country(place)):
        # "Remote" alone is kept only when the posting text mentions India somewhere.
        if in_india or re.search(r"\bindia\b", (description or "").lower()):
            return "remote", 15
        return "abroad", 0
    if in_india:
        return "india", 8
    if not place.strip():
        return "unknown", 4
    return "abroad", 0


_OTHER_COUNTRIES = ("united states", "usa", "u.s.", "uk", "united kingdom", "canada", "europe", "emea",
                    "germany", "france", "singapore", "australia", "latam", "brazil", "mexico", "japan",
                    "ireland", "netherlands", "spain", "poland", "israel", "uae", "dubai", "americas")


def _names_other_country(place: str) -> bool:
    return any(country in place for country in _OTHER_COUNTRIES)


# ---- experience ---------------------------------------------------------------------------

_RANGE = re.compile(r"(\d{1,2})\s*(?:\+)?\s*(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*(?:years|year|yrs|yr)\b", re.I)
_SINGLE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|year|yrs|yr)\b", re.I)
_CONTEXT = re.compile(r"experience|exp\b|work(?:ing)? in|background|relevant|professional|post[- ]mba|industry", re.I)


def parse_experience(text: str) -> tuple[float | None, float | None]:
    """Find the asked experience in a job description. Returns (min_years, max_years) or (None, None)."""
    if not text:
        return None, None
    candidates: list[tuple[float, float | None]] = []
    for match in _RANGE.finditer(text):
        low, high = float(match.group(1)), float(match.group(2))
        if low <= high <= 25 and _near_context(text, match):
            candidates.append((low, high))
    if not candidates:
        for match in _SINGLE.finditer(text):
            value = float(match.group(1))
            if value <= 20 and _near_context(text, match):
                candidates.append((value, None))
    if not candidates:
        return None, None
    return min(candidates, key=lambda pair: pair[0])


def _near_context(text: str, match: re.Match) -> bool:
    window = text[max(0, match.start() - 90): match.end() + 60]
    if re.search(r"years? old|founded|since \d{4}|in business|over the (last|past)|warranty", window, re.I):
        return False
    return bool(_CONTEXT.search(window))


# ---- pay ----------------------------------------------------------------------------------

_LPA_RANGE = re.compile(
    r"(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:\.\d+)?)\s*(?:l|lpa|lakhs?|lacs?)?\s*(?:-|–|—|to)\s*(?:₹|rs\.?|inr)?\s*"
    r"(\d{1,3}(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?|l\b)", re.I)
_LPA_SINGLE = re.compile(
    r"(?:up\s?to|upto|ctc(?: of)?|salary(?: of)?|package(?: of)?|₹|rs\.?|inr)\s*:?\s*(?:₹|rs\.?|inr)?\s*"
    r"(\d{1,3}(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?|l\b)", re.I)
_LPA_BARE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:lpa|lacs?|lakhs?)\b", re.I)
_RUPEES = re.compile(r"(?:₹|rs\.?|inr)\s*(\d{1,2},\d{2},\d{2},\d{3}|\d{1,2},\d{2},\d{3}|\d{6,8})", re.I)
_NOT_PAY = re.compile(r"^\s*(?:\+\s*)?(users|customers|downloads|orders|merchants|students|people|sellers|"
                      r"vehicles|units|drivers|riders|farmers|stores|retailers|subscribers|learners|"
                      r"transactions|sq|km|families|homes|businesses|msmes|smes|in (revenue|funding|gmv|arr))", re.I)


def _is_pay(text: str, match: re.Match) -> bool:
    """'5-10 lakh users' and 'Rs 50 lakh in funding' are not salaries."""
    return not _NOT_PAY.match(text[match.end(): match.end() + 30])


@dataclass
class Pay:
    stated: str | None = None
    min_lpa: float | None = None
    max_lpa: float | None = None
    basis: str = "unknown"          # stated | estimate | unknown
    source: str = ""
    fit: str = "Unknown"


def parse_pay(text: str) -> tuple[float | None, float | None, str | None]:
    """Find a stated INR annual pay. Returns (min_lpa, max_lpa, the matched text)."""
    if not text:
        return None, None, None
    for match in _LPA_RANGE.finditer(text):
        low, high = float(match.group(1)), float(match.group(2))
        if 1 <= low <= high <= 300 and _is_pay(text, match):
            return low, high, match.group(0).strip()
    match = next((m for pattern in (_LPA_SINGLE, _LPA_BARE) for m in pattern.finditer(text) if _is_pay(text, m)), None)
    if match:
        value = float(match.group(1))
        if 1 <= value <= 300:
            upto = bool(re.search(r"up\s?to", match.group(0), re.I))
            return (None if upto else value), value, match.group(0).strip()
    amounts = [int(m.group(1).replace(",", "")) for m in _RUPEES.finditer(text)]
    amounts = [a for a in amounts if 300_000 <= a <= 30_000_000]
    if amounts:
        low, high = min(amounts) / 100_000, max(amounts) / 100_000
        return round(low, 1), round(high, 1), f"Rs {min(amounts):,} - {max(amounts):,}" if low != high else f"Rs {amounts[0]:,}"
    return None, None, None


def pay_fit(min_lpa: float | None, max_lpa: float | None, floor: float, basis: str = "stated") -> str:
    if max_lpa is None and min_lpa is None:
        return "Unknown"
    top = max_lpa if max_lpa is not None else min_lpa
    bottom = min_lpa if min_lpa is not None else max_lpa
    label = "stated" if basis == "stated" else "estimate"
    if top < floor:
        return f"Below range ({label})"
    if bottom >= floor:
        return f"In range ({label})"
    return f"Possibly in range ({label})"


# ---- the verdict --------------------------------------------------------------------------

@dataclass
class Verdict:
    keep: bool
    score: int = 0
    tier: str | None = None
    reasons: list[str] = field(default_factory=list)
    reject_reason: str | None = None
    stretch: bool = False
    location_bucket: str = "unknown"
    exp_min: float | None = None
    exp_max: float | None = None
    pay: Pay = field(default_factory=Pay)


def judge(job: dict[str, Any], targeting: dict) -> Verdict:
    """Score one raw job. `job` has title, company, location, description, pay_text, posted_at."""
    title, company = job.get("title") or "", job.get("company") or ""
    description = job.get("description") or ""

    for bad in targeting["companies"]["exclude"]:
        if word_match(bad, company):
            return Verdict(False, reject_reason=f"{company} is on the exclude list")

    tier, points, stretch, reason = classify_title(title, targeting)
    if reason:
        return Verdict(False, reject_reason=reason)
    verdict = Verdict(True, tier=tier, stretch=stretch)
    verdict.score += points
    verdict.reasons.append(f"{tier} role (+{points})")

    bucket, loc_points = classify_location(job.get("location") or "", description, targeting)
    verdict.location_bucket = bucket
    if bucket == "abroad":
        return Verdict(False, tier=tier, reject_reason=f"outside India ({job.get('location')})")
    verdict.score += loc_points
    verdict.reasons.append({"bengaluru": "Bengaluru", "remote": "Remote, open to India", "india": "India, outside Bengaluru",
                            "unknown": "Location not stated"}[bucket] + f" (+{loc_points})")

    exp_cfg = targeting["experience"]
    exp_min, exp_max = parse_experience(job.get("experience_text") or "")
    if exp_min is None:
        exp_min, exp_max = parse_experience(description)
    verdict.exp_min, verdict.exp_max = exp_min, exp_max
    if exp_min is not None:
        if exp_min > exp_cfg["stretch_max_years"]:
            return Verdict(False, tier=tier, reject_reason=f"asks {exp_min:g}+ years")
        if exp_min >= exp_cfg["ideal_max_years"]:
            verdict.stretch = True
            verdict.score += 4
            verdict.reasons.append(f"Stretch: asks {exp_min:g}+ years (+4)")
        elif exp_min <= 2:
            verdict.score += 15
            verdict.reasons.append(f"Experience fits: asks {exp_min:g}+ years (+15)")
        else:
            verdict.score += 10
            verdict.reasons.append(f"Experience close: asks {exp_min:g}+ years (+10)")
    else:
        verdict.score += 7
        verdict.reasons.append("Experience not stated (+7)")
    if stretch and exp_min is None:
        verdict.score -= 6
        verdict.reasons.append("Senior-sounding title, seniority unconfirmed (-6)")

    floor = targeting["pay"]["floor_lpa"]
    low, high, matched = parse_pay(" ".join(filter(None, [job.get("pay_text"), title, description])))
    if matched:
        fit = pay_fit(low, high, floor)
        verdict.pay = Pay(stated=matched, min_lpa=low, max_lpa=high, basis="stated",
                          source=job.get("source", ""), fit=fit)
        if fit.startswith("Below"):
            return Verdict(False, tier=tier, reject_reason=f"stated pay {matched} is below Rs {floor} LPA", pay=verdict.pay)
        bonus = 20 if fit.startswith("In range") else 12
        verdict.score += bonus
        verdict.reasons.append(f"Pay {matched}: {fit} (+{bonus})")
    else:
        verdict.score += 6
        verdict.reasons.append("Pay not stated; needs evidence (+6)")

    if any(word_match(name, company) for name in targeting["companies"]["favourites"]):
        verdict.score += 6
        verdict.reasons.append("Company on the strong pay/culture list (+6)")

    if job.get("type") == "company":
        verdict.score -= 18
        verdict.reasons.append("No named opening, speculative note to founders (-18)")

    posted = parse_iso(job.get("posted_at"))
    if posted:
        age = (now() - posted).days
        if age <= 7:
            verdict.score += 5
            verdict.reasons.append("Posted in the last week (+5)")
        elif age > 30:
            verdict.score -= 8
            verdict.reasons.append(f"Posted {age} days ago, may be closed (-8)")

    verdict.score = max(0, min(100, verdict.score))
    verdict.keep = verdict.score >= targeting["scoring"]["keep_threshold"]
    if not verdict.keep:
        verdict.reject_reason = f"rule score {verdict.score} under threshold"
    return verdict

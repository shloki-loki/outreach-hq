"""Find and grade a work email for a named person at a company, on free tiers only.

Order of trust, highest first:
  published     the address appears on the company's own site or in the posting          (95)
  verified      a verification API confirmed the mailbox exists                          (90)
  hunter        Hunter's finder returned it with a good score                            (its score)
  pattern       the company's address pattern is known from a confirmed address          (70)
  catch-all     the domain accepts every address, so nothing can be confirmed            (55)
  guess         most likely pattern, the domain takes mail, nothing else known           (35)
A bounce teaches the domain's pattern list, so the same wrong guess is never made twice.

Port 25 is blocked on laptops and on GitHub's servers, so there is no direct SMTP probing here.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from typing import Any, Callable

from . import store
from .util import HttpError, ascii_fold, http_get, http_json, load_config, norm_company, now_iso, today

NOT_COMPANY_HOSTS = (
    "linkedin.com", "github.com", "medium.com", "notion.site", "notion.so", "google.com", "forms.gle",
    "angel.co", "wellfound.com", "ycombinator.com", "workatastartup.com", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "greenhouse.io", "lever.co", "ashbyhq.com", "instahyre.com",
    "naukri.com", "iimjobs.com", "hirist.tech", "cutshort.io", "workable.com", "smartrecruiters.com",
    "myworkdayjobs.com", "darwinbox.in", "darwinbox.com", "keka.com", "zohorecruit.com", "freshteam.com",
    "typeform.com", "airtable.com", "tally.so", "bit.ly", "lnkd.in", "tinyurl.com", "youtube.com",
    "talentxo.com", "hiring.cafe", "indeed.com", "foundit.in", "apna.co", "peerlist.io", "gmail.com",
)
GENERIC_LOCALS = ("careers", "career", "jobs", "hr", "hiring", "talent", "recruitment", "recruiting",
                  "people", "join", "work", "hello", "contact", "info", "team", "founders", "support")
FREE_MAIL = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "protonmail.com", "icloud.com")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

PATTERNS: dict[str, Callable[[str, str], str]] = {
    "first": lambda f, l: f,
    "first.last": lambda f, l: f"{f}.{l}",
    "firstlast": lambda f, l: f"{f}{l}",
    "flast": lambda f, l: f"{f[0]}{l}",
    "f.last": lambda f, l: f"{f[0]}.{l}",
    "first_last": lambda f, l: f"{f}_{l}",
    "firstl": lambda f, l: f"{f}{l[0]}",
    "last": lambda f, l: l,
}
ORDER_FOUNDER = ["first", "first.last", "firstlast", "flast"]
ORDER_EMPLOYEE = ["first.last", "first", "firstlast", "flast", "f.last", "first_last"]


# ---- names and domains --------------------------------------------------------------------

def _clean(part: str) -> str:
    return re.sub(r"[^a-z]", "", ascii_fold(part).lower())


def split_name(full_name: str) -> tuple[str, str]:
    """'Dr. Anand Kumar Prajapati' -> ('anand', 'prajapati'). Initials and titles are dropped."""
    parts = [p for p in re.split(r"[\s,]+", (full_name or "").strip())
             if len(_clean(p)) > 1 and _clean(p) not in ("dr", "mr", "ms", "mrs", "jr", "sr", "phd", "ca", "prof")]
    if not parts:
        return "", ""
    return _clean(parts[0]), (_clean(parts[-1]) if len(parts) > 1 else "")


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    target = url if "//" in url else f"https://{url}"
    host = (urllib.parse.urlparse(target).hostname or "").lower().removeprefix("www.")
    if "." not in host or any(host == bad or host.endswith("." + bad) for bad in NOT_COMPANY_HOSTS):
        return None
    for prefix in ("careers.", "jobs.", "apply.", "join.", "boards.", "hire.", "app."):
        if host.startswith(prefix) and host.count(".") >= 2:
            host = host[len(prefix):]
    return host


def resolve_domain(company: str, *urls: str | None) -> tuple[str | None, str]:
    """Work out the company's email domain. Returns (domain or None, how it was found)."""
    for url in urls:
        domain = domain_of(url)
        if domain:
            return domain, "from the company or posting link"
    try:
        query = urllib.parse.quote(re.sub(r"\(.*?\)", "", company).strip())
        suggestions = http_json(f"https://autocomplete.clearbit.com/v1/companies/suggest?query={query}", retries=1)
    except (HttpError, ValueError):
        return None, "lookup failed"
    wanted = norm_company(company)
    for item in suggestions or []:
        if norm_company(item.get("name")) == wanted and item.get("domain"):
            return item["domain"].lower(), "company-name lookup (exact name match)"
    return None, "no exact name match; needs the agent to find the website"


def mx_provider(domain: str) -> str | None:
    """'google', 'microsoft', 'zoho', 'other', or None when the domain takes no mail."""
    try:
        answer = http_json(f"https://dns.google/resolve?name={urllib.parse.quote(domain)}&type=MX", retries=1)
    except (HttpError, ValueError):
        return "unknown"
    hosts = " ".join(record.get("data", "").lower() for record in answer.get("Answer") or [] if record.get("type") == 15)
    if not hosts:
        return None
    if "google" in hosts or "googlemail" in hosts:
        return "google"
    if "outlook" in hosts or "protection.outlook" in hosts:
        return "microsoft"
    if "zoho" in hosts:
        return "zoho"
    return "other"


def scrape_published(domain: str) -> dict[str, list[str]]:
    """Addresses the company itself publishes on its site."""
    found: set[str] = set()
    for page in ("", "/contact", "/contact-us", "/about", "/about-us", "/careers", "/team", "/jobs"):
        try:
            body = http_get(f"https://{domain}{page}", retries=0, timeout=12).decode("utf-8", "replace")
        except HttpError:
            continue
        body = body.replace("&#64;", "@").replace("%40", "@").replace(" [at] ", "@").replace("(at)", "@")
        for address in EMAIL.findall(body):
            address = address.lower().rstrip(".")
            if address.endswith("@" + domain) and not re.search(r"\.(png|jpg|jpeg|gif|svg|webp)$", address):
                found.add(address)
    generic = sorted(a for a in found if a.split("@")[0] in GENERIC_LOCALS)
    personal = sorted(found - set(generic))
    return {"generic": generic, "personal": personal}


def infer_pattern(email: str, first: str, last: str) -> str | None:
    local = email.split("@")[0].lower()
    if not first:
        return None
    for name, build in PATTERNS.items():
        if (last or name == "first") and build(first, last or "x") == local:
            return name
    return None


def candidates(first: str, last: str, domain: str, role_type: str, known: dict | None = None) -> list[tuple[str, str]]:
    """Ordered (email, pattern) guesses, skipping patterns that already bounced at this domain."""
    known = known or {}
    order = list(ORDER_FOUNDER if role_type == "founder" else ORDER_EMPLOYEE)
    if known.get("pattern") in PATTERNS:
        order = [known["pattern"]] + [name for name in order if name != known["pattern"]]
    bad = set(known.get("bounced_patterns") or [])
    result = []
    for name in order:
        if name in bad or (not last and name != "first"):
            continue
        result.append((f"{PATTERNS[name](first, last or '')}@{domain}", name))
    return result


# ---- free-tier quotas ---------------------------------------------------------------------

class Quota:
    """Counts provider calls per day or month so free allowances are never exceeded."""

    def __init__(self) -> None:
        self.cfg = load_config("settings").get("providers", {})
        self.usage = store.load("quotas")["usage"]
        self.spent: dict[str, int] = {}

    def _bucket(self, provider: str) -> str:
        period = self.cfg[provider].get("period", "month")
        return f"{provider}:{today() if period == 'day' else today()[:7]}"

    def key(self, provider: str) -> str | None:
        return os.environ.get(self.cfg.get(provider, {}).get("env", "")) or None

    def available(self, provider: str) -> bool:
        if provider not in self.cfg or not self.key(provider):
            return False
        bucket = self._bucket(provider)
        return self.usage.get(bucket, 0) + self.spent.get(bucket, 0) < self.cfg[provider]["limit"]

    def left(self, provider: str) -> int:
        if not self.available(provider):
            return 0
        bucket = self._bucket(provider)
        return self.cfg[provider]["limit"] - self.usage.get(bucket, 0) - self.spent.get(bucket, 0)

    def spend(self, provider: str) -> None:
        bucket = self._bucket(provider)
        self.spent[bucket] = self.spent.get(bucket, 0) + 1

    def flush(self) -> None:
        if not self.spent:
            return
        spent, self.spent = self.spent, {}

        def change() -> None:
            quotas = store.load("quotas")
            for bucket, count in spent.items():
                quotas["usage"][bucket] = quotas["usage"].get(bucket, 0) + count
            store.save("quotas", quotas)
        store.transact(change, "quotas: provider usage")


# ---- providers ----------------------------------------------------------------------------
# Each verifier returns one of: valid, invalid, catch_all, unknown.

def verify_hunter(email: str, key: str) -> str:
    data = http_json("https://api.hunter.io/v2/email-verifier?" + urllib.parse.urlencode({"email": email, "api_key": key}),
                     retries=1).get("data") or {}
    status = data.get("status") or data.get("result")
    return {"valid": "valid", "deliverable": "valid", "invalid": "invalid", "undeliverable": "invalid",
            "accept_all": "catch_all"}.get(status, "unknown")


def verify_qev(email: str, key: str) -> str:
    data = http_json("https://api.quickemailverification.com/v1/verify?" + urllib.parse.urlencode({"email": email, "apikey": key}),
                     retries=1)
    if str(data.get("accept_all")).lower() == "true":
        return "catch_all"
    return {"valid": "valid", "invalid": "invalid"}.get(data.get("result"), "unknown")


def verify_reoon(email: str, key: str) -> str:
    data = http_json("https://emailverifier.reoon.com/api/v1/verify?" + urllib.parse.urlencode({"email": email, "key": key, "mode": "power"}),
                     retries=1, timeout=70)
    status = (data.get("status") or "").lower()
    if status in ("safe", "valid", "role_account"):
        return "valid"
    if status in ("invalid", "disabled", "disposable", "spamtrap"):
        return "invalid"
    return "catch_all" if status == "catch_all" else "unknown"


def verify_zerobounce(email: str, key: str) -> str:
    data = http_json("https://api.zerobounce.net/v2/validate?" + urllib.parse.urlencode({"api_key": key, "email": email, "ip_address": ""}),
                     retries=1, timeout=40)
    status = (data.get("status") or "").lower()
    return {"valid": "valid", "invalid": "invalid", "spamtrap": "invalid", "abuse": "invalid", "do_not_mail": "invalid",
            "catch-all": "catch_all"}.get(status, "unknown")


def verify_mailboxvalidator(email: str, key: str) -> str:
    data = http_json("https://api.mailboxvalidator.com/v2/validation/single?" + urllib.parse.urlencode({"email": email, "key": key, "format": "json"}),
                     retries=1, timeout=40)
    if data.get("error"):
        raise ValueError(str(data["error"])[:200])
    if str(data.get("is_catchall")).lower() == "true":
        return "catch_all"
    status = str(data.get("status")).lower()
    return "valid" if status == "true" else "invalid" if status == "false" else "unknown"


def verify_emailable(email: str, key: str) -> str:
    data = http_json("https://api.emailable.com/v1/verify?" + urllib.parse.urlencode({"email": email, "api_key": key}),
                     retries=1, timeout=40)
    if data.get("accept_all"):
        return "catch_all"
    return {"deliverable": "valid", "undeliverable": "invalid"}.get((data.get("state") or "").lower(), "unknown")


def verify_debounce(email: str, key: str) -> str:
    data = (http_json("https://api.debounce.io/v1/?" + urllib.parse.urlencode({"api": key, "email": email}),
                      retries=1, timeout=40).get("debounce") or {})
    result = (data.get("result") or "").lower()
    if "accept-all" in result or "accept all" in result:
        return "catch_all"
    return "valid" if result == "safe to send" else "invalid" if result in ("invalid", "bounce") else "unknown"


def verify_verifalia(email: str, credentials: str) -> str:
    """credentials = 'username:password' of a Verifalia (sub-)account; the free plan allows 25 a day."""
    import base64
    auth = base64.b64encode(credentials.encode()).decode()
    body = json.dumps({"entries": [{"inputData": email}]}).encode()
    data = http_json("https://api.verifalia.com/v2.6/email-validations?waitTime=30000", data=body, retries=1, timeout=45,
                     headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    entry = ((data.get("entries") or {}).get("data") or [{}])[0]
    if (entry.get("status") or "") in ("ServerIsCatchAll",):
        return "catch_all"
    return {"Deliverable": "valid", "Undeliverable": "invalid"}.get(entry.get("classification") or "", "unknown")


# Every verifier with a key and free quota left takes part. Each call goes to the one with the most quota left
# today, so the free allowances are used side by side instead of one after another.
VERIFIERS: list[tuple[str, Callable[[str, str], str]]] = [
    ("mailboxvalidator", verify_mailboxvalidator), ("verifalia", verify_verifalia), ("zerobounce", verify_zerobounce),
    ("emailable", verify_emailable), ("debounce", verify_debounce), ("quickemailverification", verify_qev),
    ("reoon", verify_reoon), ("hunter", verify_hunter)]


def hunter_find(first: str, last: str, domain: str, key: str) -> tuple[str | None, int, str]:
    params = urllib.parse.urlencode({"domain": domain, "first_name": first, "last_name": last, "api_key": key})
    data = http_json(f"https://api.hunter.io/v2/email-finder?{params}", retries=1).get("data") or {}
    verification = (data.get("verification") or {}).get("status") or ""
    return (data.get("email") or "").lower() or None, int(data.get("score") or 0), verification


def apollo_match(first: str, last: str, domain: str, key: str) -> tuple[str | None, str]:
    body = urllib.parse.urlencode({"first_name": first, "last_name": last, "domain": domain,
                                   "reveal_personal_emails": "false"}).encode()
    data = http_json("https://api.apollo.io/api/v1/people/match", data=body, retries=1,
                     headers={"x-api-key": key, "Cache-Control": "no-cache",
                              "Content-Type": "application/x-www-form-urlencoded"})
    person = data.get("person") or {}
    email = (person.get("email") or "").lower()
    if not email or "email_not_unlocked" in email:
        return None, ""
    return email, person.get("email_status") or ""


def verify(email: str, quota: Quota) -> tuple[str, str]:
    """Returns (valid|invalid|catch_all|unknown, provider used or '')."""
    for provider, check in sorted(VERIFIERS, key=lambda pc: -quota.left(pc[0])):
        if not quota.available(provider):
            continue
        quota.spend(provider)
        try:
            verdict = check(email, quota.key(provider))
        except (HttpError, ValueError) as exc:
            store.open_issue("email-finder", f"{provider} verification call failed", str(exc)[:300],
                             key=f"provider-fail:{provider}")
            continue
        if verdict != "unknown":
            return verdict, provider
    return "unknown", ""


# ---- the finder ---------------------------------------------------------------------------

def find_email(name: str, domain: str, role_type: str = "employee", quota: Quota | None = None,
               max_verifications: int = 3) -> dict[str, Any]:
    """Best available address for one person. Never raises; explains itself in `trail`."""
    quota = quota or Quota()
    trail: list[str] = []
    result = {"email": "", "email_status": "none", "email_source": "", "confidence": 0, "trail": trail}
    first, last = split_name(name)
    if not first or not domain:
        trail.append("no usable name or domain")
        return result
    if domain in FREE_MAIL:
        trail.append(f"{domain} is a personal-mail domain, not a company")
        return result

    domains = store.load("domains")["domains"]
    known = dict(domains.get(domain) or {})
    if "provider" not in known:
        known["provider"] = mx_provider(domain)
    if known["provider"] is None:
        trail.append(f"{domain} has no mail servers")
        _remember(domain, known)
        return result

    def done(email: str, status: str, source: str, confidence: int) -> dict[str, Any]:
        result.update(email=email, email_status=status, email_source=source, confidence=confidence)
        _remember(domain, known)
        quota.flush()
        return result

    for confirmed in known.get("confirmed") or []:  # someone we already know at this domain
        if infer_pattern(confirmed, first, last):
            return done(confirmed, "verified", "already confirmed for this person", 92)

    if last and quota.available("hunter"):
        quota.spend("hunter")
        try:
            email, score, state = hunter_find(first, last, domain, quota.key("hunter"))
            trail.append(f"hunter finder: {email or 'nothing'} (score {score}, {state or 'unverified'})")
            if email and state == "valid":
                known.setdefault("pattern", infer_pattern(email, first, last))
                known["confirmed"] = sorted(set(known.get("confirmed") or []) | {email})
                return done(email, "verified", "Hunter finder, verified", max(score, 90))
            if email and score >= 70:
                known.setdefault("pattern", infer_pattern(email, first, last))
                return done(email, "hunter", f"Hunter finder, score {score}", score)
        except (HttpError, ValueError) as exc:
            trail.append(f"hunter finder failed: {exc}")

    if last and quota.available("apollo"):
        quota.spend("apollo")
        try:
            email, state = apollo_match(first, last, domain, quota.key("apollo"))
            trail.append(f"apollo: {email or 'nothing'} ({state or 'no status'})")
            if email and email.endswith("@" + domain):
                status = "verified" if state == "verified" else "hunter"
                known.setdefault("pattern", infer_pattern(email, first, last))
                return done(email, status, f"Apollo ({state or 'unverified'})", 90 if state == "verified" else 72)
        except (HttpError, ValueError) as exc:
            trail.append(f"apollo failed: {exc}")
            if isinstance(exc, HttpError) and exc.status in (401, 403):
                store.open_issue("email-finder", "Apollo's free plan refused the API call",
                                 "Apollo returned 401/403. Its free tier may not include this endpoint; remove "
                                 "APOLLO_API_KEY or upgrade.", key="provider-fail:apollo")

    if "published" not in known:
        published = scrape_published(domain)
        known["published"] = published["generic"][:6]
        for address in published["personal"][:10]:
            trail.append(f"site lists {address}")
        known["site_personal"] = published["personal"][:10]
    for address in known.get("site_personal") or []:
        if infer_pattern(address, first, last):
            return done(address, "published", f"listed on {domain}", 95)

    options = candidates(first, last, domain, role_type, known)
    if not options:
        trail.append("every known pattern has bounced at this domain")
        _remember(domain, known)
        quota.flush()
        return result
    if known.get("catch_all"):
        trail.append("domain accepts every address (catch-all), so no check is possible")
        return done(options[0][0], "catch-all", f"pattern {options[0][1]} on a catch-all domain", 55)

    checked = 0
    for email, pattern in options:
        if checked >= max_verifications:
            break
        verdict, provider = verify(email, quota)
        if not provider:
            trail.append("no verifier key or free quota left")
            break
        checked += 1
        trail.append(f"{provider}: {email} is {verdict}")
        if verdict == "valid":
            known["pattern"] = pattern
            known["confirmed"] = sorted(set(known.get("confirmed") or []) | {email})
            return done(email, "verified", f"{provider} confirmed the mailbox", 90)
        if verdict == "catch_all":
            known["catch_all"] = True
            return done(options[0][0], "catch-all", f"pattern {options[0][1]} on a catch-all domain", 55)
        if verdict == "invalid":
            continue
        break

    if known.get("pattern") in PATTERNS and options[0][1] == known["pattern"]:
        return done(options[0][0], "pattern", f"company pattern is {known['pattern']} (from a confirmed address)", 70)
    remaining = [pair for pair in options][checked:] or options
    return done(remaining[0][0], "guess", f"most likely pattern ({remaining[0][1]}), not verified", 35)


def _remember(domain: str, known: dict) -> None:
    known["checked_at"] = now_iso()

    def change() -> None:
        data = store.load("domains")
        merged = dict(data["domains"].get(domain) or {})
        merged.update(known)
        data["domains"][domain] = merged
        store.save("domains", data)
    store.transact(change, f"domains: {domain}")


def learn_bounce(email: str, name: str) -> None:
    """A hard bounce: that pattern is wrong for this domain (unless it was a confirmed address)."""
    domain = email.split("@")[-1]
    first, last = split_name(name)
    pattern = infer_pattern(email, first, last)

    def change() -> None:
        data = store.load("domains")
        known = data["domains"].setdefault(domain, {})
        if pattern and known.get("pattern") != pattern:
            known["bounced_patterns"] = sorted(set(known.get("bounced_patterns") or []) | {pattern})
        known["confirmed"] = [a for a in known.get("confirmed") or [] if a != email]
        store.save("domains", data)
    store.transact(change, f"domains: bounce at {domain}")


def learn_delivered(email: str, name: str) -> None:
    """A reply proves the address and its pattern."""
    domain = email.split("@")[-1]
    first, last = split_name(name)
    pattern = infer_pattern(email, first, last)

    def change() -> None:
        data = store.load("domains")
        known = data["domains"].setdefault(domain, {})
        known["confirmed"] = sorted(set(known.get("confirmed") or []) | {email})
        if pattern:
            known["pattern"] = pattern
        store.save("domains", data)
    store.transact(change, f"domains: confirmed {domain}")

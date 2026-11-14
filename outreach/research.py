"""Lead research on GitHub with a free model, held to the same bar as the lead-scout agent.

For each unresearched lead, best first:
  1. Read the real posting (the board's own text, or the page itself). No posting text, no decision:
     the lead is left for a person or Claude, never qualified on its title.
  2. Ask Gemini, with Google Search, for evidence about the company: what it does, stage, ratings with
     review counts, pay figures for the title with their source and sample, culture flags, one recent fact.
  3. Ask a second model call to judge the lead with the lead-scout rubric (config/prompts/research.md),
     given only the posting, that evidence (each source numbered) and the facts in config/profile.toml.
  4. Check the answer in code before anything is stored (see `check`): the hook's URL must be one of the
     numbered sources, years asked are re-read from the posting, a pay estimate must name a site that the
     evidence actually reported, a qualify must cite real profile facts. Problems get one retry; a lead
     that still fails is left unresearched with a note, so a person or Claude picks it up.
  5. Store it through `record`, the same code path `lead research` uses, marked as machine research so
     Claude's review pass (routing.toml: review = claude) can sample it.

`research-run --compare L0326,L0105` runs steps 1-4 on leads Claude already researched and prints both
verdicts side by side without storing anything: the quality check before Claude's own research is retired.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import live, llm, store
from .rules import parse_experience, parse_pay, pay_fit
from .sources import linkedin
from .util import CONFIG_DIR, HttpError, clip, http_get, load_config, now_iso, strip_html, today

PROMPTS = CONFIG_DIR / "prompts"
PAY_SITES = ("ambitionbox", "glassdoor", "levels.fyi", "levels", "naukri", "weekday", "instahyre", "grapevine",
             "6figr", "linkedin", "indeed", "payscale", "wellfound", "cutshort", "the posting", "posting")


# ---- recording (shared with `lead research`) -------------------------------------------------

def record(lead_id: str, payload: dict[str, Any], by: str = "lead-scout", extra: dict | None = None) -> dict[str, Any]:
    """Validate a research payload, store it and decide qualified or rejected. Raises ValueError."""
    targeting = load_config("targeting")
    result: dict[str, Any] = {}

    def change() -> None:
        data = store.load("leads")
        lead = store.find(data["leads"], lead_id)
        if not lead:
            raise ValueError(f"no lead {lead_id}")
        research_score = payload.get("research_score")
        if not isinstance(research_score, (int, float)) or not 0 <= research_score <= 100:
            raise ValueError("research_score (0-100) is required")
        if payload.get("decision") not in ("qualify", "reject"):
            raise ValueError("decision must be 'qualify' or 'reject'")
        if payload["decision"] == "reject" and not payload.get("reject_reason"):
            raise ValueError("reject_reason is required when rejecting")
        if not payload.get("fit_notes"):
            raise ValueError("fit_notes is required")
        headline = (payload.get("headline") or "").strip()
        if not 30 <= len(headline) <= 170:
            raise ValueError("headline is required: one sentence of 30-170 characters that tells Shlok at a glance "
                             "why this is (or is not) for him")
        pay = payload.get("pay")
        if pay:
            basis = pay.get("basis", "estimate")
            if basis == "estimate" and not pay.get("source"):
                raise ValueError("an estimated pay needs its source (site, sample size, total or fixed)")
            lead["pay"] = {"stated": pay.get("stated") or lead["pay"].get("stated"),
                           "min_lpa": pay.get("min_lpa"), "max_lpa": pay.get("max_lpa"), "basis": basis,
                           "source": pay.get("source") or "",
                           "fit": pay_fit(pay.get("min_lpa"), pay.get("max_lpa"), targeting["pay"]["floor_lpa"], basis)}
        for field in ("company_domain", "company_url", "company_linkedin", "work_mode", "apply_url"):
            if payload.get(field):
                lead[field] = payload[field]
        if "open" in payload:
            lead["open"] = bool(payload["open"])
        if payload.get("jd") and not lead.get("jd"):
            lead["jd"] = payload["jd"][:3000]
        lead["research"] = {
            "done": True, "headline": headline, "fit_notes": payload["fit_notes"], "pay_notes": payload.get("pay_notes", ""),
            "culture_notes": payload.get("culture_notes", ""), "hook": payload.get("hook", ""),
            "hook_source": payload.get("hook_source", ""), "researched_at": now_iso(), "by": by, **(extra or {})}
        total = round(0.4 * lead["score"]["rules"] + 0.6 * research_score)
        lead["score"].update(research=research_score, total=total)
        below = lead["pay"]["fit"].startswith("Below")
        qualifies = payload["decision"] == "qualify" and total >= targeting["scoring"]["qualified_threshold"] \
            and not below and lead.get("open", True)
        if lead.get("stage") in ("new", "qualified", "rejected"):
            lead["stage"] = "qualified" if qualifies else "rejected"
        reason = payload.get("reject_reason") or ("pay is below the floor" if below else
                                                  "posting is closed" if not lead.get("open", True) else
                                                  f"score {total} is under {targeting['scoring']['qualified_threshold']}")
        lead["reject_reason"] = None if qualifies else reason
        store.add_timeline(lead, by, "researched", f"score {total}: " + ("qualified" if qualifies else f"rejected ({reason})"))
        store.save("leads", data)
        result.update(id=lead["id"], total=total, stage=lead["stage"], pay_fit=lead["pay"]["fit"],
                      reject_reason=lead["reject_reason"])
    store.transact(change, f"research: {lead_id}")
    return result


# ---- inputs ------------------------------------------------------------------------------------

def public_profile() -> str:
    """What the model may know about Shlok: proof points, skills, education, limits. No contact details,
    no employment list (which names the current employer), no pay."""
    profile = load_config("profile")
    lines = [f"Candidate: {profile['positioning']['one_liner']}.",
             f"Experience: about {profile['person']['years_experience']} years in total. Education: {profile['person']['education']}.",
             f"Based in {profile['person']['city']}.", "Facts (cite by id; nothing else about him may be assumed):"]
    lines += [f"- [{fact['id']}] {fact['text']}" for fact in profile["facts"]]
    lines.append("Skills: " + ", ".join(profile["skills"]["business"] + profile["skills"]["programming"]) + ".")
    lines.append("He does NOT have: " + "; ".join(profile["positioning"]["never_claim"]) + ".")
    return "\n".join(lines)


def fact_ids() -> set[str]:
    return {fact["id"] for fact in load_config("profile")["facts"]}


def posting_text(lead: dict) -> tuple[str, str]:
    """(text, url) of the real posting, or ("", reason). Prefers what the board's API already gave us."""
    url = lead.get("source_url") or lead.get("apply_url") or ""
    stored = (lead.get("jd") or "").strip()
    if len(stored) >= 400:
        return stored, url
    try:
        if lead.get("source") == "linkedin":
            detail = linkedin.fetch_detail(str(lead["source_id"]))
            text = "\n".join(filter(None, [detail["description"], " | ".join(detail["criteria"]), detail["pay_text"]]))
        elif lead.get("source") == "linkedin_post":
            return "", "a LinkedIn post needs a signed-in look"
        else:
            if not url:
                return "", "no posting URL"
            text = strip_html(http_get(url, retries=1, timeout=25).decode("utf-8", "replace"))
    except HttpError as exc:
        return "", f"could not open the posting: {exc}"
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if lead.get("type") != "company" and len(text) < 300:
        return "", "the posting page has no readable description"
    return clip(text, 9000), url


def _prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def gather_evidence(lead: dict, models: dict[str, str | None]) -> tuple[dict, list[dict]]:
    """Company and pay evidence with numbered sources. Returns (evidence, sources).

    Google Search grounding is free only on the 2.5 models, and Google no longer offers Gemini 2.5 Flash to new
    keys (2026-11). So: grounded search when a grounding model is available; otherwise the evidence is fetched
    here (the company's own site and Google News) and a model only reads it. Either way every fact must come
    with one of the numbered source URLs, which `check` enforces."""
    global _GROUNDING_OFF
    if models.get("research") and not _GROUNDING_OFF:
        try:
            return _grounded_evidence(lead, models["research"])
        except llm.LlmError as exc:
            if not re.search(r"HTTP (400|403|404)|no longer available|not supported|not enabled", str(exc), re.I):
                raise
            _GROUNDING_OFF = True  # this key cannot ground; use fetched evidence for the rest of the run
    return _fetched_evidence(lead, models["judge"])


_GROUNDING_OFF = False


def _grounded_evidence(lead: dict, model: str) -> tuple[dict, list[dict]]:
    ask = _prompt("evidence").format(
        company=lead.get("company"), title=lead.get("title"), location=lead.get("location") or "India",
        website=lead.get("company_url") or lead.get("company_domain") or "unknown",
        linkedin=lead.get("company_linkedin") or "unknown", today=today())
    reply = llm.generate(ask, model=model, search=True, temperature=0.2, max_tokens=3000)
    try:
        evidence = reply.json()
    except (llm.LlmError, json.JSONDecodeError):
        evidence = {"notes": clip(reply.text, 2500)}
    sources, seen = [], set()
    for source in reply.sources:
        url = llm.resolve(source["url"])
        if url and url not in seen and "vertexaisearch" not in url and "grounding-api-redirect" not in url:
            seen.add(url)
            sources.append({"id": f"S{len(sources) + 1}", "title": source.get("title", ""), "url": url})
    return evidence, sources[:15]


def company_site(lead: dict) -> str:
    url = (lead.get("company_url") or "").strip()
    if not url and lead.get("company_domain"):
        url = f"https://{lead['company_domain']}"
    if not re.match(r"https?://[^\s/]+\.[^\s]+$", url) or re.search(r"linkedin\.com|wellfound\.com|naukri\.com", url):
        return ""
    return url


def news(company: str, limit: int = 6) -> list[dict]:
    """Recent Google News items for the company (free RSS, no key): title, date, publisher, link."""
    name = re.sub(r"\s*\(.*?\)|\b(pvt|private|ltd|limited|inc|technologies|india)\b\.?", "", company, flags=re.I).strip(" .,-")
    if len(name) < 3:
        return []
    query = urllib.parse.quote(f'"{name}" when:180d')
    try:
        root = ET.fromstring(http_get(f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en",
                                      retries=1, timeout=20))
    except (HttpError, ET.ParseError):
        return []
    items = []
    for item in root.iter("item"):
        title, link = (item.findtext("title") or "").strip(), (item.findtext("link") or "").strip()
        if not title or not link.startswith("http"):
            continue
        if not re.search(rf"\b{re.escape(name)}\b", title, re.I):
            continue  # a headline that does not name this employer is about someone else
        source = item.find("source")
        items.append({"title": title, "link": link, "date": (item.findtext("pubDate") or "")[5:16],
                      "publisher": (source.text or "") if source is not None else ""})
        if len(items) >= limit:
            break
    return items


def _fetched_evidence(lead: dict, model: str) -> tuple[dict, list[dict]]:
    sources: list[dict] = []
    material: list[str] = []
    site = company_site(lead)
    if site:
        try:
            text = clip(re.sub(r"\n{2,}", "\n", strip_html(http_get(site, retries=1, timeout=20).decode("utf-8", "replace"))), 3500)
            if len(text) > 200:
                sources.append({"id": "S1", "title": f"{lead.get('company')} website", "url": site})
                material.append(f"[S1] {site}\n{text}")
        except HttpError:
            pass
    for item in news(lead.get("company") or ""):
        sid = f"S{len(sources) + 1}"
        sources.append({"id": sid, "title": item["title"], "url": item["link"]})
        material.append(f"[{sid}] {item['date']} {item['publisher']}: {item['title']}")
    if lead.get("company_note"):
        material.append(f"[board note, from the job board itself] {lead['company_note']}")
    if not material:
        return {"notes": "no company website or news found"}, []
    ask = _prompt("evidence_fetched").format(
        company=lead.get("company"), title=lead.get("title"), today=today(), material="\n\n".join(material)[:9000])
    reply = llm.generate(ask, model=model, json_mode=True, temperature=0.1, max_tokens=2500)
    try:
        evidence = reply.json()
    except (llm.LlmError, json.JSONDecodeError):
        evidence = {"notes": clip(reply.text, 2500)}
    evidence["evidence_mode"] = "fetched (website + Google News; no web search)"
    return evidence, sources


# ---- checks ------------------------------------------------------------------------------------

def check(payload: dict, lead: dict, posting: str, posting_url: str, evidence: dict, sources: list[dict]) -> list[str]:
    """Rules a model answer must meet before it is stored. Returns problems (empty = fine)."""
    problems: list[str] = []
    targeting = load_config("targeting")
    if payload.get("decision") not in ("qualify", "reject"):
        problems.append("decision must be qualify or reject")
    score = payload.get("research_score")
    if not isinstance(score, (int, float)) or not 0 <= score <= 100:
        problems.append("research_score must be a number 0-100")
    headline = (payload.get("headline") or "").strip()
    if not 30 <= len(headline) <= 170:
        problems.append(f"headline is {len(headline)} characters; it must be 30-170")
    if re.search(r"\b(great|exciting|amazing|fantastic|excellent) (opportunity|role|fit)\b", headline, re.I):
        problems.append("headline has an adjective verdict; state facts")
    if not (payload.get("fit_notes") or "").strip():
        problems.append("fit_notes is empty")
    if payload.get("decision") == "reject" and not payload.get("reject_reason"):
        problems.append("a reject needs reject_reason")
    allowed_urls = {s["url"] for s in sources} | ({posting_url} if posting_url else set())
    hook_source = (payload.get("hook_source") or "").strip()
    if payload.get("hook") and hook_source not in allowed_urls:
        problems.append("hook_source must be exactly the posting URL or one of the numbered source URLs")
    matched = [f for f in payload.get("matched_facts") or [] if f in fact_ids()]
    if payload.get("decision") == "qualify" and not matched:
        problems.append("a qualify must name the profile facts (ids) that answer the role's needs in matched_facts")
    unknown = [f for f in payload.get("matched_facts") or [] if f not in fact_ids()]
    if unknown:
        problems.append(f"matched_facts has ids that do not exist: {unknown}")
    pay = payload.get("pay") or {}
    if pay and (pay.get("min_lpa") or pay.get("max_lpa")):
        basis = pay.get("basis")
        if basis == "stated":
            low, high, _ = parse_pay(posting + "\n" + (lead.get("pay", {}).get("stated") or ""))
            if low is None and high is None:
                problems.append("pay basis is 'stated' but the posting states no figure; use estimate or unknown")
        elif basis == "estimate":
            text = json.dumps(evidence).lower()
            named = [site for site in PAY_SITES if site in (pay.get("source") or "").lower()]
            if not named or not any(site in text for site in named):
                problems.append("an estimated pay must name a site that the evidence reported pay from")
    if payload.get("decision") == "qualify":
        exp_min, _ = parse_experience(posting)
        if exp_min is not None and exp_min > targeting["experience"]["stretch_max_years"]:
            problems.append(f"the posting asks {exp_min:g}+ years, above the {targeting['experience']['stretch_max_years']} "
                            "year stretch limit; this must be a reject")
        if lead.get("type") != "company" and not posting:
            problems.append("cannot qualify without the posting text")
    return problems


# ---- the worker ----------------------------------------------------------------------------------

def research_one(lead: dict, models: dict[str, str]) -> dict[str, Any]:
    """Run steps 1-4 for one lead. Returns {"payload", "sources", ...} or {"skip": reason}."""
    if lead.get("source") != "linkedin_post" and lead.get("type") != "company":
        try:
            closed, why = live.probe(lead)
            if closed:
                return {"closed": why}
        except live.Unknown:
            pass
    posting, url = posting_text(lead)
    if not posting and lead.get("type") != "company":
        return {"skip": url}
    evidence, sources = gather_evidence(lead, models)
    numbered = "\n".join(f"[{s['id']}] {s['title']} {s['url']}" for s in sources) or "(no web sources returned)"
    lead_view = {k: lead.get(k) for k in ("company", "title", "location", "type", "source", "company_url", "company_note",
                                         "posted_at", "exp_min", "exp_max", "stretch", "tier")}
    lead_view["rule_reasons"] = (lead.get("score") or {}).get("reasons", [])
    lead_view["stated_pay"] = (lead.get("pay") or {}).get("stated")
    ask = _prompt("research").format(
        profile=public_profile(), lead=json.dumps(lead_view, ensure_ascii=False), posting_url=url or "(none)",
        posting=posting or "(no posting: a company with no named opening)", evidence=json.dumps(evidence, ensure_ascii=False)[:6000],
        sources=numbered, floor=load_config("targeting")["pay"]["floor_lpa"], today=today())
    payload: dict[str, Any] = {}
    problems: list[str] = []
    for attempt in range(2):
        prompt = ask if attempt == 0 else ask + "\n\nYour previous answer broke these rules; fix them and answer again:\n- " \
            + "\n- ".join(problems) + "\nPrevious answer:\n" + json.dumps(payload, ensure_ascii=False)
        reply = llm.generate(prompt, model=models["judge"], json_mode=True, temperature=0.2, max_tokens=3000)
        try:
            payload = reply.json()
        except (llm.LlmError, json.JSONDecodeError) as exc:
            problems = [f"the answer was not valid JSON: {exc}"]
            continue
        problems = check(payload, lead, posting, url, evidence, sources)
        if not problems:
            break
    if problems:
        return {"skip": "model answer failed the checks: " + "; ".join(problems)[:500], "payload": payload}
    if not payload.get("hook"):
        payload["hook_source"] = ""
    payload["open"] = True
    if posting and not lead.get("jd"):
        payload["jd"] = posting
    return {"payload": payload, "sources": sources, "evidence": evidence}


def pick_models() -> dict[str, str]:
    cfg = load_config("settings").get("llm", {})
    try:
        grounding = llm.pick(cfg.get("research_models", ["gemini-2.5-flash"]))
    except llm.LlmUnavailable:
        grounding = None  # no free grounding model for this key: evidence is fetched instead
    return {"research": grounding, "judge": llm.pick(cfg.get("judge_models", ["gemini-3.8-flash"]))}


def queue(limit: int) -> list[dict]:
    leads = [lead for lead in store.load("leads")["leads"]
             if lead.get("stage") == "new" and lead.get("open") is not False
             and not (lead.get("research") or {}).get("done")
             and (lead.get("research_attempt") or {}).get("at", "")[:10] != today()]
    leads.sort(key=lambda lead: -(lead.get("score") or {}).get("total", 0))
    return leads[:limit]


def _note_attempt(lead_id: str, why: str) -> None:
    def change() -> None:
        data = store.load("leads")
        lead = store.find(data["leads"], lead_id)
        if lead:
            lead["research_attempt"] = {"at": now_iso(), "why": why[:400], "by": "research-worker"}
            store.save("leads", data)
    store.transact(change, f"research: {lead_id} left for a person")


def _bin(lead_id: str, why: str) -> None:
    def change() -> None:
        data = store.load("leads")
        lead = store.find(data["leads"], lead_id)
        if lead and not live.in_conversation(lead):
            lead["open"] = False
            lead["bin"] = {"at": now_iso(), "reason": why, "by": "research-worker"}
            store.add_timeline(lead, "research-worker", "posting_closed", f"moved to the Bin: {why}")
            store.save("leads", data)
    store.transact(change, f"research: {lead_id} closed")


def run(limit: int = 25, ids: list[str] | None = None) -> dict[str, Any]:
    store.sync()
    stats = {"researched": 0, "qualified": 0, "rejected": 0, "binned": 0, "left_for_a_person": 0, "errors": 0}
    if not llm.key():
        title = "Research worker skipped: GEMINI_API_KEY is not set"
        if not any(e.get("title") == title and e.get("at", "")[:10] == today() for e in store.load("journal")["entries"][-200:]):
            store.log_entry("research-worker", "note", title, "Add the Gemini key as a GitHub secret to start research on GitHub.")
        return {**stats, "skipped": "GEMINI_API_KEY is not set"}
    models = pick_models()
    leads = queue(limit) if not ids else [l for l in store.load("leads")["leads"] if l["id"] in ids]
    stopped = ""
    for lead in leads:
        try:
            outcome = research_one(lead, models)
        except llm.LlmUnavailable as exc:
            stopped = str(exc)
            break
        except (llm.LlmError, HttpError, ValueError, KeyError) as exc:
            stats["errors"] += 1
            _note_attempt(lead["id"], f"error: {exc}")
            continue
        if outcome.get("closed"):
            _bin(lead["id"], outcome["closed"])
            stats["binned"] += 1
        elif outcome.get("skip"):
            _note_attempt(lead["id"], outcome["skip"])
            stats["left_for_a_person"] += 1
        else:
            payload = outcome["payload"]
            extra = {"sources": outcome["sources"], "matched_facts": payload.get("matched_facts", []),
                     "review": "pending", "model": models["judge"], "evidence_model": (outcome.get("evidence") or {}).get("evidence_mode") or models["research"]}
            try:
                result = record(lead["id"], payload, by="research-worker", extra=extra)
            except ValueError as exc:
                _note_attempt(lead["id"], f"store refused: {exc}")
                stats["left_for_a_person"] += 1
                continue
            stats["researched"] += 1
            stats["qualified" if result["stage"] == "qualified" else "rejected"] += 1
    summary = (f"{stats['researched']} researched ({stats['qualified']} qualified, {stats['rejected']} rejected), "
               f"{stats['binned']} closed postings binned, {stats['left_for_a_person']} left for a person")
    if stopped:
        summary += f"; stopped early: {stopped}"
    store.log_run("research-worker", stats["errors"] == 0, summary, {**stats, "models": models})
    return {**stats, "models": models, "stopped": stopped}


def compare(ids: list[str]) -> list[dict]:
    """Shadow run on leads that already have research: nothing is stored."""
    store.sync()
    models = pick_models()
    rows = []
    for lead in [l for l in store.load("leads")["leads"] if l["id"] in ids]:
        before = {"stage": lead.get("stage"), "score": (lead.get("score") or {}).get("research"),
                  "headline": (lead.get("research") or {}).get("headline"), "pay": (lead.get("pay") or {}).get("fit")}
        copy = json.loads(json.dumps(lead))
        copy["jd"] = lead.get("jd")
        try:
            outcome = research_one(copy, models)
        except llm.LlmUnavailable:
            raise
        except (llm.LlmError, HttpError, ValueError) as exc:
            outcome = {"skip": f"error: {exc}"[:300]}
        payload = outcome.get("payload") or {}
        rows.append({"id": lead["id"], "company": lead["company"], "title": lead["title"], "claude": before,
                     "worker": {"decision": payload.get("decision"), "score": payload.get("research_score"),
                                "headline": payload.get("headline"), "pay": payload.get("pay"),
                                "reject_reason": payload.get("reject_reason"), "hook": payload.get("hook"),
                                "hook_source": payload.get("hook_source"), "skip": outcome.get("skip"),
                                "closed": outcome.get("closed"), "sources": len(outcome.get("sources") or []),
                                "evidence_mode": (outcome.get("evidence") or {}).get("evidence_mode", "grounded search")}})
    return rows

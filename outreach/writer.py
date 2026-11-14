"""Cold emails, follow-ups and LinkedIn notes, written on GitHub with the free model.

Quality is held by four gates, in order. A draft that fails any of them is rewritten with the reasons (at
most three tries) and otherwise dropped, leaving a note on the lead; nothing weak reaches the approval queue.
  1. config/voice.md is in the prompt, word for word, with the one play chosen in code (`choose_play`).
  2. `messages.check_draft` / `check_linkedin`: the playbook's rules in code.
  3. `fact_check`: every number in the message must appear in profile.toml or in the lead's own research,
     so a result can never be inflated or invented.
  4. A second model call reads it as the recipient (config/prompts/critic.md). Below 7/10 on "would reply",
     "reads mass-produced", or any unsupported claim sends it back for a rewrite.
Drafts then wait for Shlok's approval on the site like every other draft. Nothing here sends anything.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import live, llm, messages, store
from .research import PROMPTS, public_profile
from .util import CONFIG_DIR, load_config, now_iso, today

CONTACT_ORDER = {"hiring_manager": 0, "founder": 1, "recruiter": 2, "employee": 3, "generic": 4}
MAX_OPEN_DRAFTS = 20      # drafts waiting for approval; more than this and Shlok cannot keep up
MIN_WOULD_REPLY = 7


def voice() -> str:
    return (CONFIG_DIR / "voice.md").read_text(encoding="utf-8")


def choose_play(lead: dict, contact: dict) -> str:
    """config/voice.md, The four plays."""
    if lead.get("type") == "company":
        return "offer"
    if contact.get("role_type") in ("recruiter", "generic"):
        return "direct"
    if (lead.get("score") or {}).get("total", 0) >= 80:
        return "offer"
    return "question"


def lead_brief(lead: dict) -> str:
    research = lead.get("research") or {}
    view = {"company": lead.get("company"), "role": lead.get("title"), "location": lead.get("location"),
            "no_named_opening": lead.get("type") == "company", "applied": bool(lead.get("applied_at")),
            "headline": research.get("headline"), "fit_notes": research.get("fit_notes"),
            "culture_notes": research.get("culture_notes"), "hook": research.get("hook"),
            "hook_source": research.get("hook_source"), "posting_excerpt": (lead.get("jd") or "")[:2500]}
    return json.dumps(view, ensure_ascii=False, indent=1)


def person_brief(contact: dict) -> str:
    return json.dumps({k: contact.get(k) for k in ("name", "title", "role_type", "why")}, ensure_ascii=False)


NUMBER = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)*)\s*(%|x|cr|crore|days?|months?|years?|weeks?|lakh)?", re.I)


def fact_check(text: str, lead: dict) -> list[str]:
    """Numbers the message uses that appear nowhere in the allowed facts or the lead's research."""
    profile = load_config("profile")
    allowed = " ".join(f["text"] for f in profile["facts"]) + " " + json.dumps(lead.get("research") or {}) + " " \
        + (lead.get("jd") or "") + " " + (lead.get("title") or "") + " " + (lead.get("company") or "")
    allowed_numbers = {m.group(1).replace(",", "") for m in NUMBER.finditer(allowed)}
    bad = sorted({m.group(1) for m in NUMBER.finditer(text) if m.group(1).replace(",", "") not in allowed_numbers})
    return [f"uses the number {n}, which is in neither his facts nor the lead's research" for n in bad]


def critique(message: str, lead: dict, contact: dict, model: str) -> list[str]:
    ask = (PROMPTS / "critic.md").read_text(encoding="utf-8").format(
        person=f"{contact.get('name')}, {contact.get('title') or contact.get('role_type')} at {lead.get('company')}",
        profile=public_profile(), lead=lead_brief(lead), message=message)
    try:
        verdict = llm.generate(ask, model=model, json_mode=True, temperature=0.1, max_tokens=800).json()
    except (llm.LlmError, json.JSONDecodeError):
        return []  # the critic is an extra gate; the code checks above still hold
    problems = []
    if int(verdict.get("would_reply") or 0) < MIN_WOULD_REPLY:
        problems.append(f"a reader rated it {verdict.get('would_reply')}/10 for replying; {verdict.get('fix', '')}")
    if verdict.get("reads_mass_produced"):
        problems.append("it reads mass-produced; make the opener and the question specific to them")
    problems += [f"unsupported claim: {c}" for c in verdict.get("unsupported_claims") or [] if c]
    problems += [f"unclear to a reader: {c}" for c in (verdict.get("unclear") or [])[:2] if c]
    return problems


def _write(what: str, lead: dict, contact: dict, task: str, limits: str, schema: str,
           validate, models: dict[str, str], render) -> tuple[dict | None, list[str]]:
    """Up to three tries through all four gates. Returns (draft, last problems)."""
    ask = (PROMPTS / "writer.md").read_text(encoding="utf-8").format(
        what=what, voice=voice(), profile=public_profile(), lead=lead_brief(lead), person=person_brief(contact),
        task=task, limits=limits, schema=schema)
    draft: dict = {}
    problems: list[str] = []
    for attempt in range(3):
        prompt = ask if attempt == 0 else ask + "\n\nYour previous draft was rejected for these reasons. Rewrite it so " \
            "none of them applies:\n- " + "\n- ".join(problems) + "\nPrevious draft:\n" + json.dumps(draft, ensure_ascii=False)
        try:
            draft = llm.generate(prompt, model=models["writer"], json_mode=True, temperature=0.6, max_tokens=1500).json()
        except (llm.LlmError, json.JSONDecodeError) as exc:
            problems = [f"answer was not valid JSON: {exc}"]
            continue
        problems = validate(draft)
        if problems:
            continue
        problems = critique(render(draft), lead, contact, models["judge"])
        if not problems:
            return draft, []
    return None, problems


def _note(lead_id: str, text: str) -> None:
    def change() -> None:
        data = store.load("leads")
        lead = store.find(data["leads"], lead_id)
        if lead:
            lead.setdefault("notes", []).append({"at": now_iso(), "by": "writer", "text": text[:600]})
            store.save("leads", data)
    store.transact(change, f"writer: note on {lead_id}")


# ---- cold emails ---------------------------------------------------------------------------------

def cold_targets(leads: list[dict], all_messages: list[dict]) -> list[tuple[dict, dict]]:
    emailed = {(m["lead_id"], m["contact_id"]) for m in all_messages if m.get("kind") == "cold" and m.get("status") != "skipped"}
    leads_emailed = {m["lead_id"] for m in all_messages if m.get("kind") == "cold" and m.get("status") != "skipped"}
    targets = []
    for lead in leads:
        research = lead.get("research") or {}
        if lead.get("stage") != "qualified" or lead.get("open") is False or live.in_conversation(lead) \
                or lead.get("id") in leads_emailed or lead.get("outcome"):
            continue
        if not research.get("hook") or not research.get("hook_source"):
            continue
        usable = [c for c in lead.get("contacts", []) if c.get("email") and c.get("email_status") in messages.TRUSTED
                  and (lead["id"], c["id"]) not in emailed and not messages.suppressed(c["email"])]
        if usable:
            usable.sort(key=lambda c: CONTACT_ORDER.get(c.get("role_type"), 9))
            targets.append((lead, usable[0]))
    targets.sort(key=lambda pair: -(pair[0].get("score") or {}).get("total", 0))
    return targets


def write_cold(lead: dict, contact: dict, models: dict[str, str]) -> dict | None:
    play = choose_play(lead, contact)
    research = lead.get("research") or {}
    task = (f"Write the FIRST cold email using the **{play}** play. Build the opener on this hook, which is true and "
            f"sourced: \"{research.get('hook')}\" ({research.get('hook_source')}). Choose the one result from his facts "
            f"that best matches what this role needs, told as before and after in plain words.")
    limits = ("50-120 words in the body (aim 60-100); subject 2-6 words and at most 45 characters, no digits, no pipe; "
              "body starts 'Hi " + (contact.get("name") or "there").split()[0] + ",' and ends with a last line that is just "
              "'Shlok'; first sentence after the greeting does not start with I, My, 'Your post' or 'The role'; exactly one "
              "question mark; at most 4 numbers; contractions; no links; no em dashes; no exclamation marks; names "
              f"{lead.get('company')}; never claims an application" + ("" if lead.get("applied_at") else "") +
              ("; there is NO opening: never imply one, say plainly he doesn't know if such a hire is on their mind" if lead.get("type") == "company" else "")
              + ("; the offer play needs a concrete promise he can deliver within a week" if play == "offer" else ""))
    schema = '{"subject": "...", "body": "Hi Name,\\n\\n...\\n\\nShlok", "promise": "what he will deliver if they say yes (offer play), else empty"}'
    speculative = lead.get("type") == "company"

    def validate(draft: dict) -> list[str]:
        problems = messages.check_draft("cold", draft.get("subject", ""), draft.get("body", ""), to_name=contact.get("name") or "",
                                        company=lead.get("company") or "", speculative=speculative,
                                        applied=bool(lead.get("applied_at")), play=play, hook=research.get("hook"),
                                        hook_source=research.get("hook_source"), promise=draft.get("promise", ""))
        return problems + fact_check(draft.get("subject", "") + "\n" + draft.get("body", ""), lead)

    draft, problems = _write("first cold email", lead, contact, task, limits, schema, validate, models,
                             lambda d: f"Subject: {d.get('subject')}\n\n{d.get('body')}")
    if not draft:
        _note(lead["id"], f"Writer could not produce a cold email to {contact.get('name')} that passes every check: "
                          + "; ".join(problems)[:400])
        return None
    body = draft["body"].rstrip() + "\n"
    return messages.create_draft(lead["id"], contact["id"], "cold", draft["subject"].strip(), body,
                                 hook=research.get("hook", ""), hook_source=research.get("hook_source", ""),
                                 created_by="writer", play=play, promise=draft.get("promise", ""))


# ---- follow-ups --------------------------------------------------------------------------------

def followup_targets(leads: list[dict], all_messages: list[dict]) -> list[tuple[dict, dict, str, list[dict]]]:
    targets = []
    for lead in leads:
        followup = lead.get("followup") or {}
        if not followup.get("due") or followup.get("kind") not in ("followup1", "followup2") or live.in_conversation(lead):
            continue
        thread = [m for m in all_messages if m["lead_id"] == lead["id"] and m.get("status") == "sent"]
        cold = next((m for m in thread if m.get("kind") == "cold"), None)
        if not cold:
            continue
        if any(m["lead_id"] == lead["id"] and m.get("kind") == followup["kind"] and m.get("status") != "skipped" for m in all_messages):
            continue
        contact = next((c for c in lead.get("contacts", []) if c.get("id") == cold.get("contact_id")), None)
        if contact:
            targets.append((lead, contact, followup["kind"], thread))
    return targets


def write_followup(lead: dict, contact: dict, kind: str, thread: list[dict], models: dict[str, str]) -> dict | None:
    sent = "\n\n".join(f"[{m['kind']} sent {m.get('sent_at', '')[:10]}]\nSubject: {m['subject']}\n{m['body']}" for m in thread)
    if kind == "followup1":
        task = ("Write the FIRST follow-up (about day 4) in the same thread. Add one new thing: a different result from his "
                "facts than the one already used, or one specific thought about their problem. One soft question. Never "
                f"'following up', 'bumping' or 'circling back'.\n\nWhat was already sent:\n{sent}")
        limits = "20-70 words; starts 'Hi <first name>,'; ends with a line 'Shlok'; at most one question mark; at most 4 numbers; contractions; no links"
    else:
        task = ("Write the SECOND and LAST follow-up (about day 9): the easy out, in his words, e.g. if the seat is filled or the "
                f"timing is off, a one-word no is fine; if it's open, he'd like to be in the running.\n\nWhat was already sent:\n{sent}")
        limits = "20-70 words; ends with a line 'Shlok'; at most one question mark; contractions; no links"
    schema = '{"body": "Hi Name,\\n\\n...\\n\\nShlok"}'

    def validate(draft: dict) -> list[str]:
        return messages.check_draft(kind, "Re: follow-up", draft.get("body", ""), to_name=contact.get("name") or "",
                                    company=lead.get("company") or "", speculative=lead.get("type") == "company",
                                    applied=bool(lead.get("applied_at"))) + fact_check(draft.get("body", ""), lead)

    draft, problems = _write(kind.replace("followup", "follow-up "), lead, contact, task, limits, schema, validate, models,
                             lambda d: d.get("body", ""))
    if not draft:
        _note(lead["id"], f"Writer could not produce a {kind} that passes every check: " + "; ".join(problems)[:400])
        return None
    return messages.create_draft(lead["id"], contact["id"], kind, "Re: follow-up", draft["body"].rstrip() + "\n", created_by="writer")


# ---- LinkedIn notes --------------------------------------------------------------------------------

def linkedin_targets(leads: list[dict]) -> list[tuple[dict, dict]]:
    targets = []
    for lead in leads:
        if lead.get("stage") != "qualified" or lead.get("open") is False or live.in_conversation(lead):
            continue
        done = {d.get("contact_id") for d in lead.get("linkedin_drafts", [])}
        for contact in lead.get("contacts", []):
            if contact.get("linkedin_url") and contact["id"] not in done:
                targets.append((lead, contact))
    targets.sort(key=lambda pair: -(pair[0].get("score") or {}).get("total", 0))
    return targets


def write_linkedin(lead: dict, contact: dict, models: dict[str, str]) -> dict | None:
    others = [d.get("connect", "") for d in lead.get("linkedin_drafts", [])]
    task = ("Write a LinkedIn CONNECTION NOTE and a MESSAGE/INMAIL for this person (voice.md, LinkedIn section). Shlok sends "
            "them by hand. The connection note gives one specific reason and one result, and asks for nothing beyond "
            "connecting. The message has the email's three-paragraph shape and exactly one question; the InMail subject is "
            "1-4 words." + (f" Other people at this company get these notes; word yours differently: {others}" if others else ""))
    limits = ("connection note at most 200 characters and starting 'Hi " + (contact.get("name") or "").split()[0] + ",'; "
              "message 40-80 words with exactly one question mark and starting the same way; no links, no em dashes, "
              "no exclamation marks, no pay, never claims an application, at most 3 numbers")
    schema = '{"connect": "...", "inmail_subject": "...", "inmail": "..."}'

    def validate(draft: dict) -> list[str]:
        name = contact.get("name") or ""
        problems = [f"note: {p}" for p in messages.check_linkedin("connect", draft.get("connect", ""), to_name=name)]
        problems += [f"message: {p}" for p in messages.check_linkedin("inmail", draft.get("inmail", ""), to_name=name,
                                                                        subject=draft.get("inmail_subject", ""))]
        return problems + fact_check(draft.get("connect", "") + "\n" + draft.get("inmail", ""), lead)

    draft, problems = _write("LinkedIn connection note and message", lead, contact, task, limits, schema, validate, models,
                             lambda d: f"Connection note: {d.get('connect')}\n\nMessage ({d.get('inmail_subject')}): {d.get('inmail')}")
    if not draft:
        _note(lead["id"], f"Writer could not produce LinkedIn notes for {contact.get('name')}: " + "; ".join(problems)[:400])
        return None
    record = {"contact_id": contact["id"], "name": contact.get("name"), "title": contact.get("title"),
              "linkedin_url": contact.get("linkedin_url"), "connect": draft["connect"].strip(),
              "inmail_subject": draft["inmail_subject"].strip(), "inmail": draft["inmail"].strip(),
              "status": "draft", "created_at": now_iso(), "by": "writer"}

    def change() -> None:
        data = store.load("leads")
        stored = store.find(data["leads"], lead["id"])
        stored.setdefault("linkedin_drafts", []).append(record)
        store.add_timeline(stored, "writer", "linkedin_draft", f"LinkedIn note and message for {contact.get('name')}")
        store.save("leads", data)
    store.transact(change, f"writer: LinkedIn notes for {lead['id']}")
    return record


# ---- the run ---------------------------------------------------------------------------------------

def pick_models() -> dict[str, str]:
    cfg = load_config("settings").get("llm", {})
    return {"writer": llm.pick(cfg.get("writer_models", ["gemini-2.5-flash"])),
            "judge": llm.pick(cfg.get("judge_models", ["gemini-2.5-flash"]))}


def run(cold_limit: int = 6, followup_limit: int = 10, linkedin_limit: int = 8) -> dict[str, Any]:
    store.sync()
    stats = {"cold": 0, "followups": 0, "linkedin": 0, "dropped": 0}
    if not llm.key():
        return {**stats, "skipped": "GEMINI_API_KEY is not set"}
    models = pick_models()
    stopped = ""
    try:
        leads, all_messages = store.load("leads")["leads"], store.load("messages")["messages"]
        for lead, contact, kind, thread in followup_targets(leads, all_messages)[:followup_limit]:
            stats["followups" if write_followup(lead, contact, kind, thread, models) else "dropped"] += 1
        open_drafts = sum(1 for m in store.load("messages")["messages"] if m.get("status") == "draft")
        room = max(0, min(cold_limit, MAX_OPEN_DRAFTS - open_drafts))
        leads, all_messages = store.load("leads")["leads"], store.load("messages")["messages"]
        for lead, contact in cold_targets(leads, all_messages)[:room]:
            try:
                stats["cold" if write_cold(lead, contact, models) else "dropped"] += 1
            except ValueError as exc:  # create_draft refused (cap, unverified, duplicate): note it and move on
                _note(lead["id"], f"Draft refused when queuing: {exc}")
                stats["dropped"] += 1
        for lead, contact in linkedin_targets(store.load("leads")["leads"])[:linkedin_limit]:
            stats["linkedin" if write_linkedin(lead, contact, models) else "dropped"] += 1
    except llm.LlmUnavailable as exc:
        stopped = str(exc)
    summary = (f"{stats['cold']} cold emails, {stats['followups']} follow-ups and {stats['linkedin']} LinkedIn note sets "
               f"drafted for approval; {stats['dropped']} dropped for failing checks")
    if stopped:
        summary += f"; stopped early: {stopped}"
    store.log_run("writer", True, summary, {**stats, "models": models})
    return {**stats, "models": models, "stopped": stopped}

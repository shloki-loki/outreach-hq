"""Command line for the pipeline. The agents and the GitHub workflows drive everything through it.

    python -m outreach <command> --help
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import digest, emailfinder, importers, leads as lead_model, live, messages, metrics, people, research, scout, send, store, track, writer
from .rules import Pay, Verdict, judge, pay_fit
from .util import load_config, load_env, now, now_iso, parse_iso


def out(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=1, default=str))


def read_json(source: str) -> Any:
    return json.loads(sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8"))


# ---- leads --------------------------------------------------------------------------------

def cmd_lead_list(args: argparse.Namespace) -> None:
    store.sync()
    all_messages = store.load("messages")["messages"]
    rows = []
    for lead in store.load("leads")["leads"]:
        mine = [m for m in all_messages if m["lead_id"] == lead["id"]]
        status = lead_model.display_status(lead, mine)
        if args.stage and lead.get("stage") != args.stage:
            continue
        if args.status and status != args.status:
            continue
        if args.unresearched and lead.get("research", {}).get("done"):
            continue
        if args.needs_email and (lead.get("stage") != "qualified" or any(c.get("email") for c in lead.get("contacts", []))):
            continue
        if args.speculative and lead.get("type") != "company":
            continue
        if args.stale:
            checked = parse_iso(lead.get("research", {}).get("researched_at"))
            fresh = checked and (now() - checked).days < 10
            if lead.get("stage") != "qualified" or fresh or status in ("offer", "interview", "replied"):
                continue
        if args.needs_draft and not (lead.get("stage") == "qualified" and status == "qualified" and lead.get("open", True)
                                     and any(c.get("email") and c.get("email_status") not in ("bounced", "invalid")
                                             for c in lead.get("contacts", []))):
            continue
        if args.followup_due and not lead.get("followup", {}).get("due"):
            continue
        rows.append({"id": lead["id"], "score": lead["score"]["total"], "status": status, "company": lead["company"],
                     "title": lead["title"], "location": lead["location"], "pay": lead["pay"]["fit"],
                     "source": lead["source"], "open": lead.get("open", True), "type": lead.get("type", "job"),
                     "contacts": len(lead.get("contacts", [])),
                     "emails": sum(1 for c in lead.get("contacts", []) if c.get("email"))})
    rows.sort(key=lambda row: -row["score"])
    out(rows[: args.limit] if args.limit else rows)


def cmd_lead_show(args: argparse.Namespace) -> None:
    store.sync()
    lead = store.find(store.load("leads")["leads"], args.id)
    if not lead:
        sys.exit(f"no lead {args.id}")
    mine = [m for m in store.load("messages")["messages"] if m["lead_id"] == args.id]
    out({"lead": lead, "messages": mine, "status": lead_model.display_status(lead, mine)})


def cmd_lead_add(args: argparse.Namespace) -> None:
    """Add leads an agent found by its own means. Input: one job object or a list (see sources/__init__.py)."""
    payload = read_json(args.json)
    jobs = payload if isinstance(payload, list) else [payload]
    targeting = load_config("targeting")
    report: list[dict] = []

    def change() -> None:
        report.clear()
        data = store.load("leads")
        by_key = {lead["key"]: lead for lead in data["leads"]}
        for job in jobs:
            for field in ("source", "company", "title"):
                if not job.get(field):
                    raise ValueError(f"job is missing '{field}': {job}")
            job.setdefault("source_id", job.get("url") or f"{job['company']}:{job['title']}")
            verdict = judge(job, targeting)
            if not verdict.keep and not args.force:
                report.append({"company": job["company"], "title": job["title"], "added": False,
                               "reason": verdict.reject_reason})
                continue
            if not verdict.keep:  # forced in by the agent: keep its tier guess honest
                verdict = Verdict(True, score=max(verdict.score, 45), tier=verdict.tier or "4 - Other",
                                  reasons=[f"Added by agent despite rule: {verdict.reject_reason}"],
                                  location_bucket=verdict.location_bucket, pay=verdict.pay or Pay())
            key = lead_model.lead_key(job["company"], job["title"], verdict.location_bucket)
            if key in by_key:
                lead_model.merge_job(by_key[key], job, verdict)
                report.append({"company": job["company"], "title": job["title"], "added": False,
                               "reason": f"already stored as {by_key[key]['id']}", "id": by_key[key]["id"]})
                continue
            lead = lead_model.new_lead(job, verdict, store.next_id(data["leads"], "L"))
            data["leads"].append(lead)
            by_key[key] = lead
            report.append({"company": job["company"], "title": job["title"], "added": True, "id": lead["id"],
                           "score": verdict.score})
        store.save("leads", data)
    store.transact(change, f"lead add: {len(jobs)} from agent")
    out(report)


def cmd_lead_research(args: argparse.Namespace) -> None:
    """Record research on one lead and decide qualified / rejected (same code path as the GitHub worker)."""
    out(research.record(args.id, read_json(args.json), by=args.by))


def cmd_lead_set(args: argparse.Namespace) -> None:
    def change() -> None:
        data = store.load("leads")
        lead = store.find(data["leads"], args.id)
        if not lead:
            raise ValueError(f"no lead {args.id}")
        if args.stage:
            lead["stage"] = args.stage
            store.add_timeline(lead, args.by, "stage", args.stage)
        if args.outcome:
            lead["outcome"] = None if args.outcome == "none" else args.outcome
            store.add_timeline(lead, args.by, "outcome", args.outcome)
        if args.applied:
            lead["applied_at"] = lead.get("applied_at") or now_iso()
            lead["apply"]["status"] = "applied"
            store.add_timeline(lead, args.by, "applied", "application submitted")
        if args.apply_status:
            lead["apply"]["status"] = args.apply_status
            store.add_timeline(lead, args.by, "apply", args.apply_status)
        if args.apply_answers:
            lead["apply"]["answers"] = read_json(args.apply_answers)
            store.add_timeline(lead, args.by, "apply_kit", "application answers prepared")
        if args.closed:
            lead["open"] = False
            store.add_timeline(lead, args.by, "posting_closed", "confirmed closed")
        if args.reopen:
            lead["open"] = True
            lead.pop("bin", None)
            store.add_timeline(lead, args.by, "reopened", "taken out of the Bin")
        if args.verified:
            lead["research"]["researched_at"] = now_iso()
            lead["open"] = True
            store.add_timeline(lead, args.by, "researched", "re-checked: posting is still live")
        if args.headline:
            lead["research"]["headline"] = args.headline.strip()[:170]
            lead["updated_at"] = now_iso()
        if args.note:
            lead.setdefault("notes", []).append({"at": now_iso(), "by": args.by, "text": args.note})
            lead["updated_at"] = now_iso()
        store.save("leads", data)
    store.transact(change, f"lead set: {args.id}")
    print(f"updated {args.id}")


# ---- contacts and emails ------------------------------------------------------------------

def cmd_contact_add(args: argparse.Namespace) -> None:
    result: dict[str, Any] = {}

    def change() -> None:
        data = store.load("leads")
        lead = store.find(data["leads"], args.lead)
        if not lead:
            raise ValueError(f"no lead {args.lead}")
        for contact in lead.get("contacts", []):
            if args.name and contact.get("name", "").lower() == args.name.lower():
                for field in ("title", "linkedin_url", "why"):
                    if getattr(args, field, None):
                        contact[field] = getattr(args, field)
                if args.email:
                    contact.update(email=args.email.lower(), email_status=args.email_status or "published",
                                   email_source=args.email_source or "", confidence=95 if not args.email_status else 60)
                store.save("leads", data)
                result.update(id=contact["id"], updated=True)
                return
        contact = lead_model.new_contact({
            "name": args.name or "", "title": args.title or "", "role_type": args.role_type,
            "linkedin_url": args.linkedin_url or "", "email": args.email or "",
            "email_status": (args.email_status or "published") if args.email else None,
            "email_source": args.email_source or "", "confidence": 95 if args.email and not args.email_status else 0,
            "why": args.why or ""}, lead_model.next_contact_id(lead))
        lead.setdefault("contacts", []).append(contact)
        store.add_timeline(lead, "email-finder", "contact_added", f"{contact['name'] or contact['email']} ({contact['role_type']})")
        store.save("leads", data)
        result.update(id=contact["id"], updated=False)
    store.transact(change, f"contact: {args.lead}")
    out(result)


def cmd_find_email(args: argparse.Namespace) -> None:
    store.sync()
    if args.name and args.domain:
        out(emailfinder.find_email(args.name, args.domain, args.role_type or "employee"))
        return
    if not args.lead:
        sys.exit("give --lead (and optionally --contact), or --name with --domain")
    lead = store.find(store.load("leads")["leads"], args.lead)
    if not lead:
        sys.exit(f"no lead {args.lead}")
    domain = (args.domain or "").lower().removeprefix("www.") or lead.get("company_domain")
    how = "given on the command line" if args.domain else "stored on the lead"
    if not domain:
        domain, how = emailfinder.resolve_domain(lead["company"], lead.get("company_url"), lead.get("apply_url"))
    if not domain:
        out({"lead": args.lead, "error": f"company domain unknown ({how}). Find the company's website, then run: "
                                           f"python -m outreach lead research ... with company_domain, or pass --domain."})
        return
    quota = emailfinder.Quota()
    results = []
    for contact in lead.get("contacts", []):
        if args.contact and contact["id"] != args.contact:
            continue
        settled = ("published", "verified") if args.recheck else ("published", "verified", "hunter", "pattern", "guess", "catch-all")
        if not contact.get("name") or (contact.get("email") and contact.get("email_status") in settled):
            continue
        found = emailfinder.find_email(contact["name"], domain, contact.get("role_type") or "employee", quota)
        results.append({"contact": contact["id"], "name": contact["name"], **found})
    quota.flush()

    def change() -> None:
        moved.clear()
        data = store.load("leads")
        message_file = store.load("messages")
        pending = [m for m in message_file["messages"] if m.get("status") in ("draft", "approved")]
        fresh = store.find(data["leads"], args.lead)
        fresh["company_domain"] = domain if args.domain else (fresh.get("company_domain") or domain)
        for item in results:
            contact = store.find(fresh.get("contacts", []), item["contact"])
            if contact and item["email"]:
                previous = contact.get("email")
                contact.update(email=item["email"], email_status=item["email_status"],
                               email_source=item["email_source"], confidence=item["confidence"])
                # Drafts not yet sent follow the contact to its better address and grade.
                for message in pending:
                    if message["lead_id"] == args.lead and message["contact_id"] == contact["id"]:
                        message["to"], message["email_status"] = item["email"], item["email_status"]
                        if previous and previous != item["email"]:
                            moved.append(f"{message['id']}: {previous} -> {item['email']}")
                store.add_timeline(fresh, "email-finder", "email_found",
                                   f"{contact['name']}: {item['email']} ({item['email_status']}, {item['confidence']})")
        store.save("leads", data)
        store.save("messages", message_file)
    moved: list[str] = []
    if results or args.domain:
        store.transact(change, f"emails: {args.lead}")
    published = (store.load("domains")["domains"].get(domain) or {}).get("published") or []
    out({"lead": args.lead, "domain": domain, "domain_from": how, "company_addresses": published, "results": results,
         "drafts_updated": moved})


# ---- messages and referrals ---------------------------------------------------------------

def cmd_message_draft(args: argparse.Namespace) -> None:
    body = sys.stdin.read() if args.body_file == "-" else Path(args.body_file).read_text(encoding="utf-8")
    try:
        message = messages.create_draft(args.lead, args.contact, args.kind, args.subject, body, hook=args.hook or "",
                                        hook_source=args.hook_source or "", created_by=args.by,
                                        attach_resume=args.attach_resume, allow_unverified=args.allow_unverified,
                                        play=args.play, promise=args.promise or "")
    except ValueError as exc:
        out({"queued": False, "problems": str(exc).split("; ")})
        sys.exit(2)
    out({"queued": True, "id": message["id"], "to": message["to"], "subject": message["subject"],
         "words": messages.word_count(body)})


def cmd_message_check(args: argparse.Namespace) -> None:
    body = sys.stdin.read() if args.body_file == "-" else Path(args.body_file).read_text(encoding="utf-8")
    problems = messages.check_draft(args.kind, args.subject, body, to_name=args.to_name or "", company=args.company or "",
                                    speculative=args.speculative, play=args.play, hook=args.hook,
                                    hook_source=args.hook_source, promise=args.promise)
    out({"ok": not problems, "problems": problems, "words": messages.word_count(body)})
    sys.exit(0 if not problems else 2)


def cmd_message_list(args: argparse.Namespace) -> None:
    store.sync()
    rows = [m for m in store.load("messages")["messages"] if not args.status or m.get("status") == args.status]
    if args.lead:
        rows = [m for m in rows if m["lead_id"] == args.lead]
    out(rows if args.full else [{k: m.get(k) for k in ("id", "lead_id", "contact_id", "to", "kind", "status", "subject",
                                                       "sent_at", "error")} for m in rows])


def cmd_referral_note(args: argparse.Namespace) -> None:
    text = (sys.stdin.read() if args.text_file == "-" else Path(args.text_file).read_text(encoding="utf-8")).strip()
    profile = load_config("profile")
    problems = []
    if not 120 <= len(text) <= 700:
        problems.append(f"note is {len(text)} characters; keep it 120-700")
    for hidden in profile["positioning"]["hide_in_messages"]:
        if hidden.lower() in text.lower():
            problems.append(f"mentions {hidden}")
    for pattern, label in messages.BANNED:
        if label in ("exclamation mark", "pay or notice period in a cold email"):
            continue  # a friendly note to someone he knows may be warmer than a cold email
        import re
        if re.search(pattern, text, re.I):
            problems.append(f"contains {label}")
    if problems:
        out({"saved": False, "problems": problems})
        sys.exit(2)

    def change() -> None:
        data = store.load("leads")
        lead = store.find(data["leads"], args.lead)
        if not lead:
            raise ValueError(f"no lead {args.lead}")
        referral = next((r for r in lead.get("referrals", []) if r.get("linkedin_url") == args.url or r.get("name") == args.url), None)
        if not referral:
            raise ValueError(f"{args.lead} has no connection {args.url}")
        referral["note"] = text
        store.add_timeline(lead, "referral", "referral_note", f"note drafted for {referral['name']}")
        store.save("leads", data)
    store.transact(change, f"referral note: {args.lead}")
    out({"saved": True})


# ---- issues, runs, health -----------------------------------------------------------------

def cmd_issue(args: argparse.Namespace) -> None:
    if args.action == "list":
        store.sync()
        out([i for i in store.load("issues")["issues"] if args.all or i.get("status") == "open"])
    elif args.action == "add":
        store.open_issue(args.agent, args.title, args.detail or "", args.severity)
        print("recorded")
    else:
        def change() -> None:
            data = store.load("issues")
            issue = store.find(data["issues"], args.id)
            if not issue:
                raise ValueError(f"no issue {args.id}")
            if args.remedy:
                issue["remedy"] = args.remedy
            if args.action == "resolve":
                issue.update(status="resolved", resolved_at=now_iso())
            store.save("issues", data)
            if args.action == "resolve":
                store.journal(args.agent, "fix", f"Solved: {issue['title']}", issue.get("remedy") or "", issue["id"])
            elif args.remedy:
                store.journal(args.agent, "debug", f"Diagnosis: {issue['title']}", args.remedy, issue["id"])
        store.transact(change, f"issue {args.action}: {args.id}")
        print(f"{args.action}d {args.id}")


def cmd_log(args: argparse.Namespace) -> None:
    if args.action == "add":
        if not args.title:
            sys.exit("give --title (and --detail)")
        try:
            store.log_entry(args.by, args.kind, args.title, args.detail or "", args.ref or "")
        except ValueError as exc:
            sys.exit(str(exc))
        print("logged")
        return
    store.sync()
    entries = store.load("journal")["entries"]
    if args.only:
        entries = [e for e in entries if e.get("kind") in args.only.split(",")]
    if args.since:
        entries = [e for e in entries if e.get("at", "") >= args.since]
    out(entries[-args.limit:])


def cmd_run_log(args: argparse.Namespace) -> None:
    store.log_run(args.agent, not args.fail, args.summary)
    print("logged")


def cmd_status(args: argparse.Namespace) -> None:
    store.sync()
    numbers = metrics.compute()
    runs = store.load("runs")["runs"]
    latest: dict[str, dict] = {}
    for run in runs:
        latest[run["agent"]] = run
    out({"mode": load_config("settings")["mode"], "numbers": numbers,
         "last_runs": {agent: {"at": run["at"], "ok": run["ok"], "summary": run["summary"]} for agent, run in latest.items()},
         "open_issues": [i["title"] for i in store.load("issues")["issues"] if i.get("status") == "open"]})


def cmd_doctor(args: argparse.Namespace) -> None:
    """Check that everything the pipeline needs is in place."""
    import os
    from . import mailbox
    checks: list[tuple[str, bool, str]] = []
    for name in ("profile", "targeting", "settings", "companies"):
        try:
            load_config(name)
            checks.append((f"config/{name}.toml", True, "ok"))
        except Exception as exc:
            checks.append((f"config/{name}.toml", False, str(exc)))
    profile = load_config("profile")
    checks.append(("LinkedIn profile URL in profile.toml", bool(profile["person"].get("linkedin")), "needed for forms and referral notes"))
    local = load_config("profile").get("private", {})
    checks.append(("config/profile.local.toml (CTC, notice period)", bool(local.get("current_ctc")), "needed before any form is filled"))
    checks.append(("data store is a synced git checkout", store.git_enabled(), "run scripts/setup_data.sh after the GitHub repo exists"))
    try:
        mailbox.check_login(mailbox.from_env("check"))
        checks.append(("Gmail login (SMTP + IMAP)", True, "ok"))
    except mailbox.NotConfigured as exc:
        checks.append(("Gmail login (SMTP + IMAP)", False, str(exc)))
    except Exception as exc:
        checks.append(("Gmail login (SMTP + IMAP)", False, f"{type(exc).__name__}: {exc}"))
    providers = load_config("settings")["providers"]
    have = [name for name, cfg in providers.items() if os.environ.get(cfg["env"])]
    checks.append(("email verifier keys", bool(have), ", ".join(have) or "none set: addresses will be unverified guesses"))
    connections = store.load("connections")
    checks.append(("LinkedIn connections imported", bool(connections["connections"]), f"{len(connections['connections'])} connections"))
    checks.append(("resume PDF in assets/", send.RESUME.exists(), str(send.RESUME)))
    checks.append(("mode", True, load_config("settings")["mode"]))
    width = max(len(name) for name, _, _ in checks)
    for name, ok, note in checks:
        print(f"{'OK  ' if ok else 'TODO'} {name.ljust(width)}  {note}")


def cmd_discover(args: argparse.Namespace) -> None:
    """Find which job-board system a company uses, by trying its name as a slug."""
    import re
    from .sources import ashby, greenhouse, lever
    for name in args.names:
        variants = dict.fromkeys([name.lower(), re.sub(r"[^a-z0-9]", "", name.lower()), re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")])
        hits = []
        for slug in variants:
            for system, module in (("greenhouse", greenhouse), ("lever", lever), ("ashby", ashby)):
                count = module.probe(slug)
                if count:
                    hits.append(f"{system}: \"{slug}\" ({count} jobs)")
        print(f"{name}: " + ("; ".join(dict.fromkeys(hits)) or "not on Greenhouse, Lever or Ashby under that name"))


def main(argv: list[str] | None = None) -> None:
    load_env()
    parser = argparse.ArgumentParser(prog="python -m outreach", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scout", help="read every free job source, store what passes the rules")
    p.add_argument("--only", help="comma-separated sources: greenhouse,lever,ashby,linkedin,instahyre,yc")
    p.add_argument("--dry", action="store_true", help="print what would be stored, store nothing")
    p.set_defaults(func=lambda a: out(scout.run(a.only.split(",") if a.only else None, a.dry)))

    p = sub.add_parser("research-run", help="research unresearched leads with the free model (GitHub worker)")
    p.add_argument("--limit", type=int, default=25); p.add_argument("--lead", help="comma-separated lead ids")
    p.add_argument("--compare", help="comma-separated researched lead ids: shadow run, prints both verdicts, stores nothing")
    p.set_defaults(func=lambda a: out(research.compare(a.compare.split(",")) if a.compare
                                      else research.run(limit=a.limit, ids=a.lead.split(",") if a.lead else None)))

    p = sub.add_parser("write-run", help="draft cold emails, follow-ups and LinkedIn notes with the free model, for approval")
    p.add_argument("--cold", type=int, default=6); p.add_argument("--followups", type=int, default=10)
    p.add_argument("--linkedin", type=int, default=8)
    p.add_argument("--apply", type=int, default=25, help="application cover notes for qualified jobs not yet applied to")
    p.set_defaults(func=lambda a: out(writer.run(cold_limit=a.cold, followup_limit=a.followups, linkedin_limit=a.linkedin,
                                                 apply_limit=a.apply)))

    p = sub.add_parser("people-run", help="find up to 3 people per qualified lead on LinkedIn (Apify, capped)")
    p.add_argument("--limit", type=int, default=8); p.add_argument("--lead", help="comma-separated lead ids")
    p.set_defaults(func=lambda a: out(people.run(limit=a.limit, ids=a.lead.split(",") if a.lead else None)))

    p = sub.add_parser("verify-live", help="open every lead's posting; move the closed ones to the Bin")
    p.add_argument("--limit", type=int); p.add_argument("--dry", action="store_true"); p.add_argument("--lead")
    p.set_defaults(func=lambda a: out(live.run(limit=a.limit, dry=a.dry, only=a.lead)))

    sub.add_parser("track", help="read the inbox for replies and bounces, mark follow-ups due").set_defaults(func=lambda a: out(track.run()))
    sub.add_parser("send", help="send approved emails (respects mode, caps and window)").set_defaults(func=lambda a: out(send.run()))

    def cycle(_: argparse.Namespace) -> None:
        result = {"track": track.run(), "send": send.run(), "referrals": importers.match_connections()}
        result["metrics"] = {k: v for k, v in metrics.snapshot().items() if not isinstance(v, dict)}
        out(result)
    sub.add_parser("cycle", help="track, then send, then refresh referrals and metrics").set_defaults(func=cycle)

    p = sub.add_parser("digest", help="email the morning digest")
    p.add_argument("--print", action="store_true", dest="print_only")
    p.set_defaults(func=lambda a: print(digest.run(a.print_only)["body"]) if a.print_only else out({k: v for k, v in digest.run().items() if k != "body"}))

    sub.add_parser("metrics", help="store today's numbers").set_defaults(func=lambda a: out(metrics.snapshot()))
    sub.add_parser("status", help="numbers, last runs and open issues").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="check setup").set_defaults(func=cmd_doctor)
    sub.add_parser("mail-test", help="send a test email to yourself").set_defaults(func=lambda a: print(send.test_email()))
    sub.add_parser("import-legacy", help="import the earlier tracker batches and do-not-email list").set_defaults(
        func=lambda a: out({"leads": importers.import_legacy(), "do_not_email": importers.import_suppression()}))
    p = sub.add_parser("import-connections", help="import LinkedIn's Connections.csv export")
    p.add_argument("csv")
    p.set_defaults(func=lambda a: out(importers.import_connections(a.csv)))
    p = sub.add_parser("discover", help="find a company's job-board slug")
    p.add_argument("names", nargs="+")
    p.set_defaults(func=cmd_discover)

    lead = sub.add_parser("lead", help="list, show, add, research, update leads").add_subparsers(dest="action", required=True)
    p = lead.add_parser("list")
    p.add_argument("--stage", choices=lead_model.STAGES)
    p.add_argument("--status", choices=lead_model.STATUSES)
    p.add_argument("--unresearched", action="store_true")
    p.add_argument("--needs-email", action="store_true", help="qualified leads with no email address yet")
    p.add_argument("--needs-draft", action="store_true", help="qualified, has an address, nothing drafted")
    p.add_argument("--followup-due", action="store_true")
    p.add_argument("--speculative", action="store_true", help="only companies with no named opening")
    p.add_argument("--stale", action="store_true", help="qualified leads not re-checked in the last 10 days")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_lead_list)
    p = lead.add_parser("show"); p.add_argument("id"); p.set_defaults(func=cmd_lead_show)
    p = lead.add_parser("add"); p.add_argument("--json", required=True, help="file path or - for stdin")
    p.add_argument("--force", action="store_true", help="keep it even if a rule would drop it")
    p.set_defaults(func=cmd_lead_add)
    p = lead.add_parser("research"); p.add_argument("id"); p.add_argument("--json", required=True)
    p.add_argument("--by", default="lead-scout")
    p.set_defaults(func=cmd_lead_research)
    p = lead.add_parser("set"); p.add_argument("id")
    p.add_argument("--stage", choices=lead_model.STAGES)
    p.add_argument("--outcome", choices=["interview", "offer", "rejected", "closed", "none"])
    p.add_argument("--applied", action="store_true")
    p.add_argument("--apply-status", choices=["not_started", "kit_ready", "prefilled", "applied", "blocked"])
    p.add_argument("--apply-answers", help="JSON file of prepared application answers")
    p.add_argument("--closed", action="store_true")
    p.add_argument("--reopen", action="store_true", help="take a lead out of the Bin")
    p.add_argument("--headline", help="the one-line verdict shown on the lead's header")
    p.add_argument("--verified", action="store_true", help="stamp that the posting was opened today and is still live")
    p.add_argument("--note")
    p.add_argument("--by", default="agent")
    p.set_defaults(func=cmd_lead_set)

    contact = sub.add_parser("contact", help="add or update a person on a lead").add_subparsers(dest="action", required=True)
    p = contact.add_parser("add"); p.add_argument("lead")
    p.add_argument("--name"); p.add_argument("--title")
    p.add_argument("--role-type", default="employee", choices=["recruiter", "hiring_manager", "founder", "employee", "generic"])
    p.add_argument("--linkedin-url"); p.add_argument("--email")
    p.add_argument("--email-status", choices=["published", "verified", "pattern", "guess", "catch-all"])
    p.add_argument("--email-source"); p.add_argument("--why")
    p.set_defaults(func=cmd_contact_add)

    p = sub.add_parser("find-email", help="find and grade emails for a lead's contacts")
    p.add_argument("--lead"); p.add_argument("--contact"); p.add_argument("--name"); p.add_argument("--domain")
    p.add_argument("--recheck", action="store_true", help="verify again addresses that are still guesses or unconfirmed")
    p.add_argument("--role-type")
    p.set_defaults(func=cmd_find_email)

    message = sub.add_parser("message", help="draft, check, list emails").add_subparsers(dest="action", required=True)
    for name, func in (("draft", cmd_message_draft), ("check", cmd_message_check)):
        p = message.add_parser(name)
        p.add_argument("--kind", required=True, choices=messages.KINDS)
        p.add_argument("--subject", required=True)
        p.add_argument("--body-file", required=True, help="file path or - for stdin")
        p.add_argument("--play", choices=messages.PLAYS, help="cold emails: which play from config/voice.md")
        p.add_argument("--promise", help="offer play: what Shlok will deliver if they say yes")
        if name == "check":
            p.add_argument("--hook"); p.add_argument("--hook-source")
        if name == "draft":
            p.add_argument("--lead", required=True); p.add_argument("--contact", required=True)
            p.add_argument("--hook", help="the specific fact the opener is built on")
            p.add_argument("--hook-source", help="URL where that fact was read")
            p.add_argument("--attach-resume", action="store_true")
            p.add_argument("--allow-unverified", action="store_true",
                           help="queue a draft to an unverified address (top leads only; 2 a day are sent)")
            p.add_argument("--by", default="send-track")
        else:
            p.add_argument("--to-name"); p.add_argument("--company")
            p.add_argument("--speculative", action="store_true", help="the company has no named opening")
        p.set_defaults(func=func)
    p = message.add_parser("list"); p.add_argument("--status"); p.add_argument("--lead"); p.add_argument("--full", action="store_true")
    p.set_defaults(func=cmd_message_list)

    referral = sub.add_parser("referral", help="LinkedIn-connection referrals").add_subparsers(dest="action", required=True)
    referral.add_parser("match").set_defaults(func=lambda a: out(importers.match_connections()))
    p = referral.add_parser("note"); p.add_argument("--lead", required=True)
    p.add_argument("--url", required=True, help="the connection's LinkedIn URL (or exact name)")
    p.add_argument("--text-file", required=True)
    p.set_defaults(func=cmd_referral_note)

    p = sub.add_parser("issue", help="the supervisor's issue log")
    p.add_argument("action", choices=["list", "add", "remedy", "resolve"])
    p.add_argument("--id"); p.add_argument("--agent", default="supervisor"); p.add_argument("--title"); p.add_argument("--detail")
    p.add_argument("--severity", default="warn", choices=["info", "warn", "error"]); p.add_argument("--remedy")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_issue)

    p = sub.add_parser("log", help="the supervisor's log: every run, problem, diagnosis, fix and change")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("--by", default="supervisor"); p.add_argument("--title"); p.add_argument("--detail")
    p.add_argument("--kind", default="update", choices=["update", "debug", "fix", "review", "note"])
    p.add_argument("--ref", help="an issue, lead or commit this is about")
    p.add_argument("--only", help="list: comma-separated kinds, e.g. issue,failed,debug,fix")
    p.add_argument("--since", help="list: entries at or after this ISO date or time")
    p.add_argument("--limit", type=int, default=60)
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("run-log", help="record that an agent ran")
    p.add_argument("agent"); p.add_argument("--summary", required=True); p.add_argument("--fail", action="store_true")
    p.set_defaults(func=cmd_run_log)

    from . import supervisor
    p = sub.add_parser("supervisor", help="shared deterministic supervisor report")
    p.add_argument("--record", action="store_true", help="record health check in shared log")
    p.set_defaults(func=lambda a: out(supervisor.report(a.record)))
    p = sub.add_parser("packet", help="assemble existing research, drafts and answers for a lead")
    p.add_argument("id")
    p.set_defaults(func=lambda a: out(supervisor.packet(a.id)))
    p = sub.add_parser("work", help="shared Codex/Claude ownership and handoff queue")
    p.add_argument("action", choices=["list", "add", "claim", "assign", "release", "done"])
    p.add_argument("--id"); p.add_argument("--lead"); p.add_argument("--kind", choices=supervisor.KINDS)
    p.add_argument("--owner", choices=supervisor.WORKERS)
    p.add_argument("--title", default=""); p.add_argument("--detail", default=""); p.add_argument("--ref", default="")
    p.set_defaults(func=lambda a: out(supervisor.queue(a.action, ident=a.id, kind=a.kind, lead=a.lead,
        owner=a.owner or (supervisor.routing().get(a.kind) if a.action == "add" else None),
        title=a.title, detail=a.detail, ref=a.ref)))

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, store.StoreOffline, store.StoreBusy, store.StoreCorrupt, store.PushConflict) as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()

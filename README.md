# Outreach HQ

Shlok's job-search pipeline: find well-paid roles that fit, find the right person, write a personal
email, send it only after approval, follow up, and show where every lead stands.

```
 job boards + company career pages ─► rules ─► lead-scout researches ─► qualified lead
                                                      │
                                people + graded email addresses (email-finder)
                                                      │
        send-track drafts ──► Approvals page ──► you approve ──► sender workflow ──► Gmail
                                                      │
     tracker reads replies and bounces ─► follow-up drafts ─► you approve ─► sent in the same thread
                                                      │
                      supervisor: metrics, health of every agent, issues and remedies
```

## The four agents (`.claude/agents/`)

| Agent | Does | Never does |
|---|---|---|
| **lead-scout** (+ **email-finder**) | Researches each stored role against the resume, finds pay and culture evidence, the people to write to and their addresses; qualifies or rejects with reasons | Contact anyone, spend past free tiers, invent an address |
| **send-track** (referral + apply assistant) | Writes each cold email and queues it for approval; drafts informal LinkedIn referral notes; prepares application answers; prefills a form when asked | Send, press Submit, create accounts, enter passwords |
| **follow-up** | Drafts the follow-up for quiet threads (4 business days, then 7), flags replies | Send, answer replies |
| **supervisor** | Checks every run, data and site consistency, conversion numbers; logs issues with remedies | Approve, change mode, raise caps |

Deterministic work runs on GitHub Actions (`.github/workflows/`): `scout` reads the job sources four
times a day, `cycle` tracks the inbox and sends approved emails, `digest` emails the morning summary.

## Safety rules built into the code

- Nothing is emailed without an approval click on the website. `mode = "dry_run"` sends nothing at all.
- One sender at a time; a message is claimed before it is sent and is never re-sent silently.
- Caps: 15 new emails and 10 follow-ups a day, at most 3 a day to unverified addresses, 08:00-21:00 IST Mon-Sat.
- One cold email per person per 60 days, two people per lead, a do-not-email list, bounces block the address.
- A reply stops the thread and drops anything queued for that person.
- Every draft is checked before it can be queued: only resume facts, no mention of the current employer,
  no pay, no filler, no placeholders (`outreach/messages.py`, `config/voice.md`).
- The website is password-protected, the repo is private, secrets live only in GitHub and Vercel settings.

## Layout

| Path | What |
|---|---|
| `config/` | profile (facts), targeting (what a good lead is), settings (caps, cadence), companies (career boards), voice (how emails are written) |
| `outreach/` | the pipeline, Python standard library only. `python3 -m outreach --help` |
| `outreach/sources/` | Greenhouse, Lever, Ashby, LinkedIn public search, Instahyre, Y Combinator |
| `web/` | the Next.js site (Leads, Approvals, Progress, Log), deployed on Vercel |
| `data/` | checkout of the `data` branch: the JSON store every part reads and writes |
| `tests/` | `python3 -m unittest discover -s tests` |

First-time setup is in [SETUP.md](SETUP.md).

## The supervisor log

`data/journal.json`, shown on the site's Log page. Agent runs, new issues, diagnoses (`issue remedy`) and fixes
(`issue resolve`) are written to it automatically; anything else is added with
`python3 -m outreach log add --by <who> --kind update|debug|fix|review|note --title "..." --detail "..."`.
Read it with `python3 -m outreach log list [--only issue,failed,debug,fix] [--since 2026-11-13] [--limit 60]`.

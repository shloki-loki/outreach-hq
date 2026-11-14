# Outreach HQ: handoff for any person or model contributing

Last updated 2026-11-13 (evening, IST). Repository: `github.com/shloki-loki/outreach-hq` (private).
Live site: https://outreach-hq-psi.vercel.app (password-protected).

Read this file, then `CLAUDE.md` / `AGENTS.md` (the short rules), then `config/voice.md` (the email quality
contract). Run `python3 -m outreach status` and `python3 -m outreach log list --limit 40` for the current
state; this file describes the design and the plan, and those two commands describe today.

---

## 1. What this is and who it is for

Shlok Agrawal (IIT Guwahati 2025, a year in Strategy and Operations Planning at Ola Electric, now in a
Founder's Office role he wants to leave) is looking for a job. Applying, cold emailing and following up by
hand had become impossible to track. Outreach HQ is his job-search system: it finds roles, researches them,
finds the right people and their email addresses, drafts outreach in his voice, sends what he approves,
tracks replies, and shows everything on one website.

**His goal, in his words:** a job that is high paying, at a really good company with a good work culture
(startup or large company, either is fine), as fast as possible, with the first three mattering more than
speed. He must be able to see progress. "Do not make any mistakes."

**Targets:** fixed pay of Rs 24.5 LPA or more; Bengaluru or remote first, other Indian cities lower.
Roles in priority order: (1) Strategy and Operations, Founder's Office, CEO's Office, Chief of Staff,
BizOps, EIR; (2) Product, Program, Business Development; (3) APM and analyst roles. He has about 1.3 years
of experience: roles asking up to 3 years fit, 3-4 is a stretch, more is out. He has SQL; he has no MBA and
no consulting background.

**What matters most to him right now (2026-11-13):**
1. **The quality of the emails must go up and must never go down**, whoever writes them. He found the first
   drafts too plain and formulaic. `config/voice.md` (playbook v2) is the answer and is binding.
2. **Everything scheduled must run on GitHub, not in the Claude app**, because the Claude jobs eat his plan's
   usage. Quality must not drop when that happens.
3. A wider set of lead sources, every lead checked daily to be still open, and LinkedIn drafts for people at
   each company.

## 2. Decisions already made (do not re-ask, do not change without him)

| Topic | Decision |
|---|---|
| Sending | The system drafts. **He approves each email on the website; only then is it sent.** He wants this to become more automatic later, on his say, for a narrow class (verified address, real opening, score above a bar he sets). Not yet. |
| Sender | His Gmail `111shlokagrawal@gmail.com` through an App Password, capped (15 new + 10 follow-ups a day, 6 per run, 60-120 s apart, 08:00-21:00 IST, Mon-Sat). |
| Mode | `config/settings.toml` `mode = "live"` since 2026-11-12. Do not switch it. |
| Applying to job forms | Prefill only; he submits. No account creation, passwords or CAPTCHAs by any agent. |
| LinkedIn | **Nothing is ever sent or automated on LinkedIn.** The system drafts notes; he copies and sends. |
| Budget | **Free tiers only** (Apify free credit, Reoon free checks, GitHub free minutes, Vercel hobby). Bounce rate must stay low. |
| His current employer | **Beltech never appears in any email or note.** He is presented through Ola Electric. Application forms that ask get the real answer. |
| Facts | Only what is in `config/profile.toml` (mirrors his resume). Nothing invented, rounded up or implied. |
| Email addresses | Almost every email goes to a verified or published address. Addresses printed in a posting are used as they are and never sent to a verifier. At most 2 unverified sends a day. |
| Privacy | Private repository; the site keeps its password (the Approve button sends from his Gmail). |
| Secrets | Passwords, App Passwords, tokens and API keys are entered by him only. Never ask for them in chat, never print them, never commit them. |
| Alerts | Daily email digest plus badges on the site. |
| Record-keeping | The supervisor log records everything: every run, problem, diagnosis, fix and change. |

## 3. How it is built

Python 3.12, standard library only (no pip installs). Next.js 16 + React 19 for the site. No database.

```
config/            profile.toml (the only facts allowed), targeting.toml (what a good lead is),
                   settings.toml (mode, caps, verifier quotas), companies.toml (ATS board slugs),
                   voice.md (email playbook v2: the quality contract), profile.local.toml (private, gitignored)
outreach/          the pipeline (python3 -m outreach ...)
  cli.py           every command
  store.py         JSON store with a cross-process lock; transact(change, message); supervisor log
  rules.py         rule scoring of a posting (title tier, location, experience, pay)
  sources/         greenhouse, lever, ashby, linkedin (guest job search), instahyre, yc
  scout.py         gather -> shortlist -> store leads
  leads.py         lead and contact shapes; display_status (mirrored in web/lib/status.js)
  emailfinder.py   find and verify an address (published -> known -> patterns -> Reoon); bounce learning
  messages.py      check_draft (voice.md rules in code) and create_draft
  send.py          claim-before-send Gmail SMTP sender with caps and window
  track.py         Gmail IMAP: replies, bounces, auto-replies; marks follow-ups due
  digest.py, metrics.py, importers.py, mailbox.py, util.py
tests/             python3 -m unittest discover -s tests   (45 tests; must stay green)
web/               the site: Leads, lead page, Approvals, Progress, Log
.github/workflows/ scout.yml (4x a day), cycle.yml (track + send, 8x a day, also fired by Approve),
                   digest.yml (daily), tests.yml, mail-test.yml
.claude/agents/    lead-scout, email-finder, send-track, follow-up, supervisor (instructions for the
                   Claude agents that today do the research and writing; to be replaced, see section 6E)
data/              NOT in main. A git worktree of the `data` branch (scripts/setup_data.sh creates it)
```

**The data store.** JSON files on the `data` branch: `leads`, `messages`, `connections`, `seen`, `domains`,
`suppression` (2,592 do-not-email addresses), `quotas`, `issues`, `runs`, `journal` (the supervisor log),
`metrics`. Three kinds of writer touch it: GitHub Actions, the website (through the GitHub Contents API),
and local commands. **Every write goes through `store.transact`**, which locks, syncs to the remote branch,
applies the change, checks the JSON parses, commits, pushes, and retries on conflict. Never edit `data/` by
hand or with git. On 2026-11-13 two processes wrote `leads.json` at once and a mangled file was committed;
the lock, unique temp files and the parse check were added because of that.

**A lead's life.** `new` (scraped, passed the rules) -> researched -> `qualified` or `rejected` (total score
= 0.4 x rules + 0.6 x research; qualify at 65) -> people found -> addresses found and verified -> draft
(`check_draft` must pass) -> he approves on the site -> sent -> reply / bounce / follow-up due -> outcome
(interview, offer, rejected, closed). Leads with no opening are `type: company` ("speculative").

**Email address grades:** published 95, verified 90, hunter, pattern 70, catch-all 55, guess 35. Verifier in
use: Reoon (free: 20 checks a day, the system uses at most 18; key in local `.env` as `REOON_API_KEY`).
QuickEmailVerification refuses Gmail signups for free credits; Hunter and Apollo are wired in but have no
key.

**The website** (`web/`, Vercel root directory `web`, env `SITE_PASSWORD`, `GITHUB_TOKEN`, `GITHUB_REPO`,
`DATA_BRANCH`): Leads (counter strip, views, one-sentence verdict per row), a lead's page (what to do, the
email, people, LinkedIn connections, why it fits, application answers, notes, history), Approvals (edit,
approve, skip, approve several), Progress (funnel, reply and bounce rates, by source, agent health), Log
(the supervisor log). Auth is checked inside every page and server action.

**Secrets that exist:** GitHub Actions has `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` and variable `SITE_URL`.
Local `.env` (gitignored) has the Gmail pair, `SITE_URL` and `REOON_API_KEY`. **GitHub does not yet have
`GEMINI_API_KEY`, `APIFY_TOKEN` or `REOON_API_KEY`**; the workflows skip each step cleanly until its key is
added (he adds them himself).

## 4. Where things stand

### 2026-11-14 evening: v2 enforced, live check, new sources, GitHub workers

Built in one change (section 6 A-E): playbook v2 in code, daily live check with a Bin (13 binned on the first
run), Naukri/Wellfound/Hiring Cafe through Apify, LinkedIn people and notes, research and writing on GitHub
with Gemini's free tier. 360 leads: 264 unresearched and open, 58 qualified, 13 in the Bin. 6 emails sent,
1 reply (a recruiter for an undisclosed AI company; he has a call on Monday 2026-11-16), 0 bounces.
Waiting on him: `GEMINI_API_KEY`, `APIFY_TOKEN`, `REOON_API_KEY` as GitHub secrets.

### 2026-11-14 shared supervisor rollout

Read SUPERVISOR.md first for cross-model ownership, changes, commands and current dependencies.
Implemented work queue with claims and handoffs, configurable preferred owners, packet assembly,
deterministic GitHub supervisor workflow and PR test trigger. A local Codex app worker is now scheduled daily at 12:15 IST for explicitly assigned work; its first scheduled run is unverified. Claude desktop schedules are unchanged. Codex is the preferred owner for new queued research/writing;
Claude remains the existing scheduled worker until a replacement is verified. Both models accept user
issues as supervisor and share improvements via PRs, the work queue and journal.

### Historical snapshot: 2026-11-13 evening

- 321 leads: 248 not yet researched, 46 qualified and untouched, 13 rejected, 4 contacted, 1 applied.
  Sources: LinkedIn job search 125, Instahyre 62, old tracker of LinkedIn hiring posts 58, YC 45, Ashby 17,
  Greenhouse 8, Lever 6.
- **First emails went out today:** 4 sent after his approval (Oleria, Carbon Trail, Sugar.fit, an
  undisclosed AI company through a recruiter). 0 replies, 0 bounces so far. These four were written under
  the old playbook; their follow-ups fall due around 2026-11-19 and must follow playbook v2.
- **8 drafts wait on the Approvals page, all written under the old playbook** (Leucine, a manufacturing
  Chief of Staff role through CareerTree, WarpDrive, Helium Air, Ghost Kitchens, GBG, Vianaar, Deccan AI).
  They should be rewritten under v2 before he approves them (section 6A).
- Scheduled today: GitHub runs scout, cycle (inbox + send) and digest. Four Claude tasks on his Mac run
  research (09:27), drafting (10:30), follow-up drafting (11:30) and the supervisor (20:10). **He wants
  these four off Claude** (section 6E). Until they are replaced they are the only thing doing research and
  writing; do not switch them off before the replacement works.
- Not yet arrived or supplied: LinkedIn `Connections.csv` (he requested the full archive); a founders'
  email list he will provide (companies with no opening) for the speculative track.

## 5. What has been done so far

- 2026-11-14: Shared supervisor implementation prepared; see SUPERVISOR.md for validation and rollout boundaries.

1. Built the pipeline, data store, website and five agent definitions; imported 58 roles from his old
   tracker and a do-not-email list; went live on Vercel and GitHub Actions (2026-11-12).
2. Connected Gmail for sending and reply/bounce detection; verified end to end.
3. Added the speculative track (companies with no opening), verified-address rules, stale-lead
   re-verification, and a one-sentence verdict on every lead row.
4. Connected the Reoon verifier and ran it live (found that Sugar.fit's mail runs on `sugarfit.com`).
5. Repaired the damaged leads file, re-applied lost research, and made the store safe for concurrent
   writers.
6. Added the supervisor log (`journal.json`, the site's Log page, automatic entries for runs, issues,
   diagnoses and fixes, a daily review by the supervisor).
7. Researched cold-email practice across articles, newsletters, X and Reddit and wrote playbook v2
   (`config/voice.md`).

## 6. What is planned, in priority order

Each item says what done looks like. Where a design choice is already made, follow it.

### A-E: built on 2026-11-14 (branch `claude/playbook-live-research`), what remains

All five are code with tests (`tests/test_workers.py`, plus the v2 cases in `tests/test_pipeline.py`).
What is still open in each is listed; do not rebuild what exists.

**A. Playbook v2 enforced.** `check_draft` refuses every v2 violation (50-120 words, subject 2-6 words and
45 characters with no digits, opener not on himself except the direct play, exactly one question, at most 4
numbers, the v2 banned phrases and shapes, stiff forms, self-disqualifying lines, more than 1.3 years
claimed, missing hook or hook URL, missing play, offer without promise). `message draft --play --promise`;
the site shows play and promise. voice.md's own worked examples are a test, so the two cannot drift.
Open: metrics by play on the Progress page once 30 emails are out; follow-up timing change (optional).
The 5 drafts approved on 2026-11-14 were written under v1 and were approved before v2; leave them.

**B. Daily live check and Bin.** `verify-live` (`outreach/live.py`, `live.yml` daily 05:40 IST). Bins only on
a clear signal: board API 404/410, LinkedIn's "No longer accepting applications", a page that says the job
is closed/filled/expired, a closed Google Form. "Until the position is filled" is not a closure (a test).
Rate limits and login walls are "could not check". Conversations are never binned. `lead set <id>
--reopen` undoes it. First run 2026-11-14: 353 checked, 13 binned, 65 not checkable (34 LinkedIn posts
with no outside apply link, 27 companies with no posting). Site: Bin view on Leads.
Open: LinkedIn hiring posts with no outside link cannot be checked without a login.

**C. Naukri, Wellfound, Hiring Cafe.** `outreach/sources/apify.py`, run inside the scout workflow when
`APIFY_TOKEN` is a secret: `valig/naukri-jobs-scraper`, `clearpath/wellfound-api-ppe`,
`memo23/apify-hiring-cafe-scraper` (each test-run on 2026-11-14; Hiring Cafe found Exotel's Chief of Staff
to the CTO). Searches and cadence in `config/targeting.toml [apify.*]`. Budget: `maxTotalChargeUsd` per call
and `settings.toml [apify] monthly_cap_usd = 3.5`, checked against Apify's own monthly usage figure before
every call. Open: needs `APIFY_TOKEN` in GitHub secrets; YC not widened.

**D. LinkedIn people and notes.** `people-run` (`outreach/people.py`, harvestapi/linkedin-company-employees,
Short mode, about $0.044 a company) adds up to 3 people per qualified lead: reports-to (Chief of Staff,
strategy/business head, COO), founder/CEO, recruiter. `write-run` drafts a connection note (<=200 chars)
and a message/InMail for each, checked by `messages.check_linkedin`; shown on the lead page with copy
buttons. Never sent by the system. Open: needs `APIFY_TOKEN`; leads without `company_linkedin` are skipped.

**E. Research and writing on GitHub.** GitHub Models was retired on 2026-07-30 (docs checked), so the
workers use **Google's Gemini free tier** (`outreach/llm.py`, key `GEMINI_API_KEY`): Gemini 2.5 Flash with
Google Search grounding (free up to 500 grounded requests a day) for evidence, and the best available free
Flash model for judging and writing (`settings.toml [llm]`, picked from what the key can use). Free-tier
prompts may be used by Google to improve its products; prompts carry public postings and the facts in
profile.toml only (no contact details, no employment list, no Beltech; a test checks this).
- `research-run` (`outreach/research.py`, prompts in `config/prompts/`): reads the real posting, gathers
  sourced evidence, judges with the lead-scout rubric, then **code checks** the answer: hook URL must be
  the posting or a numbered search source, years asked re-read from the posting (over 4 = reject), an
  estimated pay must name a site the evidence reported, a qualify must cite real profile fact ids. One
  retry; otherwise the lead is left for a person with a note. Stored through the same `record` path as
  `lead research`, marked `by: research-worker`, `review: pending`.
- `write-run` (`outreach/writer.py`): cold emails, follow-ups, LinkedIn notes. Gates: voice.md in the
  prompt, play chosen in code, `check_draft`, an invented-number guard (`fact_check`), and a recipient-read
  critic (below 7/10, mass-produced, or any unsupported claim sends it back; 3 tries, then dropped with a
  note). At most 20 drafts wait for approval at once.
- `research.yml` runs research, people, email finding and writing at 07:00, 13:00, 19:00 IST.
- **Quality gate before retiring the Claude tasks:** run `research-run --compare <20 Claude-researched
  ids>` and compare decisions, scores and headlines; read the first 20 writer drafts against voice.md.
  Only then switch off the Mac's Claude research/drafting tasks. Until then both run; `create_draft`
  refuses duplicates, so they cannot double-email.
Open: `GEMINI_API_KEY` secret (he creates it in Google AI Studio); the compare run; the supervisor still
runs on Claude (its checks are mostly deterministic already in `outreach/supervisor.py`).

### F. Smaller open items

- Import the founders' email list when he supplies it (speculative track; verify addresses first; columns
  unknown yet).
- Import `Connections.csv` when it arrives: `python3 -m outreach import-connections <path>`.
- An auto-approve switch for a narrow class of emails, only when he asks.
- Pay evidence is missing for several researched leads. AiSteth (L0090) missed the qualify bar by one
  point (64 vs 65); he has not said whether to put it back.
- 264 leads are unresearched (2026-11-14, after the Bin); research-run works through them best first once
  `GEMINI_API_KEY` is set (about 80 a day on the free tier).

## 7. How to contribute without lowering quality

The project is on GitHub so several people and models can work on it. These rules are what keeps the
output from degrading.

1. **Work on a branch and open a pull request**; do not push to `main`. `tests.yml` must pass.
2. **Run the tests** before and after: `python3 -m unittest discover -s tests`. Add a test for every rule
   or behaviour you add. Standard library only; do not add dependencies.
3. **Never loosen `check_draft`, the caps, the verified-address rule or the do-not-email list** to get
   something through. Tighten, or leave alone.
4. **Emails:** follow `config/voice.md` exactly. Use only facts in `config/profile.toml`. A hook needs a
   source URL you actually opened. If you cannot say something specific and true, do not draft.
5. **Never send, approve, or switch `mode`.** Never post, message or log in anywhere on his behalf. Never
   enter or request a credential. Never mention Beltech in a message.
6. **Data only through the commands** (`python3 -m outreach ...`). One command at a time; they queue behind
   a lock. If a write fails, stop and file an issue; do not repair `data/` with git.
7. **Verify before claiming.** Open the real posting before qualifying a lead. Run the command before
   saying it works. Say plainly what you did not test.
8. **Record every change** in the supervisor log before you finish:
   `python3 -m outreach log add --by <who> --kind update|fix|debug|note --title "..." --detail "..." --ref <commit or id>`
   Problems: `issue add`, then `issue remedy` with the cause, then `issue resolve` once verified gone.
9. **Spend nothing.** Free tiers only, with a cap on every paid-per-use call and the spend tracked.
10. **Keep this file current.** When you finish or start something in section 6, update sections 4-6.

## 8. Commands you will use

```
python3 -m outreach status | doctor | metrics
python3 -m outreach scout [--only greenhouse,yc] [--dry]
python3 -m outreach lead list [--unresearched --needs-email --needs-draft --stale --speculative --limit N]
python3 -m outreach lead show <id>
python3 -m outreach lead research <id> --json <file>      # research_score, decision, fit_notes, headline...
python3 -m outreach lead set <id> [--closed --verified --headline ... --note ... --by <who>]
python3 -m outreach contact add <lead> --name ... --title ... --role-type ... [--email ... --email-source ...]
python3 -m outreach find-email --lead <id> [--recheck] [--domain example.com]
python3 -m outreach message check|draft|list ...            # draft is refused unless check_draft passes
python3 -m outreach track | send | cycle | digest --print
python3 -m outreach verify-live [--limit N] [--lead L0123] [--dry]   # daily live check, closed -> Bin
python3 -m outreach research-run [--limit N] [--lead ids] [--compare ids]   # Gemini research worker
python3 -m outreach people-run [--limit N] [--lead ids]             # LinkedIn people via Apify (capped)
python3 -m outreach write-run [--cold N --followups N --linkedin N]  # drafts for approval, never sends
python3 -m outreach issue list|add|remedy|resolve ...
python3 -m outreach log add|list ...
python3 -m unittest discover -s tests
```

Local setup: clone, run `scripts/setup_data.sh` to attach the `data` branch at `./data`, copy `.env.example`
to `.env` (he fills in the secrets). The site: `cd web && npm install && DATA_DIR=../data npm run dev`.

## 9. Known gaps and things never run for real

- Hunter and Apollo code paths were written from documentation and never run (no keys).
- Form prefilling exists only as instructions to an agent; never exercised.
- The four emails sent on 2026-11-13 are the first real sends; reply and bounce tracking is verified for
  login and parsing but has seen no real reply yet.
- `REOON_API_KEY` is not in GitHub Actions, so address verification only works from his Mac today.
- The site's Log page was checked on a local copy, not signed in on the live site.
- Reddit cannot be read by ordinary fetch tools; the research used an Apify Reddit scraper.
- The Gemini workers (`research-run`, `write-run`) are tested with a fake model only; they have never run
  against the real API (no key yet). Model names in `settings.toml [llm]` are matched against the key's
  model list at run time. The Apify job sources and people search were test-run through Apify's own tools,
  not yet through `sources/apify.py` with a token. `users/me/limits` (Apify usage read) is unverified; if it
  fails the code falls back to its own spend ledger.
- The LinkedIn-notes card on the lead page has been built but not seen with real data.

Rollout: PR #1 merged; GitHub supervisor run 43584199808 succeeded. Website packet added in follow-on PR; see SUPERVISOR.md for current limits.

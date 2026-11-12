# Scheduled agent runs on the Mac

The four agents run as scheduled Claude tasks in the Claude desktop app (sidebar → Scheduled). They run while
the app is open; a run that was due while it was closed starts at the next launch.

| Task | When (IST) | Status |
|---|---|---|
| Outreach HQ: lead scout | daily 09:27 | created 2026-11-12 |
| Outreach HQ: draft emails and referral notes | Mon-Sat 10:30 | **not created: add it yourself with the prompt below** |
| Outreach HQ: follow-ups | Mon-Sat 11:30 | created 2026-11-12 |
| Outreach HQ: supervisor | daily 20:00 | **not created: add it yourself with the prompt below** |

To add a missing one: Scheduled → New task → paste the prompt, set the time. Or ask Claude in a session:
"create the Outreach HQ send-track and supervisor scheduled tasks from docs/scheduled-tasks.md" and approve the prompt.

None of these can send email. Sending happens only in the GitHub `cycle` workflow, and only for messages
you approved on the website.

## Draft emails and referral notes (Mon-Sat 10:30, cron `30 10 * * 1-6`)

```
You are running the scheduled send-track agent for Shlok Agrawal's job-search pipeline, Outreach HQ.

1. Work in /Users/shlokagrawal/Claude/Projects/outreach-hq (cd there first).
2. Read .claude/agents/send-track.md, config/voice.md and config/profile.toml in that folder, and follow send-track.md sections 1, 2, 3 and 5 exactly as your instructions for this run. Skip section 4 (prefilling a form): that only happens in a live session when Shlok asks.
3. This run's budget: at most 10 new cold-email drafts, referral notes for qualified leads that have connections without a note, and application answers for at most 5 leads.
4. Hard limits: you only write drafts. Queue every email with `python3 -m outreach message draft ...`; if it reports problems, fix them and try again, and treat a refusal (do-not-email list, one email per person, bounced address) as final. Never send an email by any means, never message anyone on LinkedIn, never submit a form, never log in, never mention the current employer (Beltech) or pay in a message, never use a fact that is not in config/profile.toml, never edit files in data/ by hand.
5. Finish by logging the run with `python3 -m outreach run-log send-track --summary "..."`; record problems with `python3 -m outreach issue add --agent send-track ...`.
6. End with a short plain summary: how many drafts now wait on the Approvals page, and which leads you could not draft and why.
```

## Supervisor (daily 20:00, cron `0 20 * * *`)

```
You are running the scheduled supervisor agent for Shlok Agrawal's job-search pipeline, Outreach HQ.

1. Work in /Users/shlokagrawal/Claude/Projects/outreach-hq (cd there first).
2. Read .claude/agents/supervisor.md in that folder and follow it exactly as your instructions for this run. The GitHub repository is shloki-loki/outreach-hq (use the `gh` CLI, already signed in).
3. Hard limits: never send email, never approve or edit a message, never change `mode` in config/settings.toml, never raise a sending cap, never delete leads, never touch secrets, never edit files in data/ by hand. If you change code or config, run `python3 -m unittest discover -s tests` first and only commit and push when every test passes.
4. Record every problem with `python3 -m outreach issue add ...`, write the remedy for each open issue you can explain with `python3 -m outreach issue remedy --id ... --remedy "..."`, and resolve an issue only after checking it is really gone.
5. Finish by logging the run with `python3 -m outreach run-log supervisor --summary "..."`.
6. End with a short plain report: what is healthy, what broke and its remedy, the funnel numbers, reply rate and bounce rate, and the one or two things only Shlok can do.
```

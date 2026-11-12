# Scheduled agent runs on the Mac

The four agents run as scheduled Claude tasks in the Claude desktop app (sidebar → Scheduled). They run while
the app is open; a run that was due while it was closed starts at the next launch. They are saved in Auto
mode (they act without asking first); change that by editing the task in the app.

| Task | When (IST) | What it produces |
|---|---|---|
| Outreach HQ: lead scout | daily 09:27 | researched, qualified or rejected leads, with people and addresses |
| Outreach HQ: draft emails and referral notes | Mon-Sat 10:30 | email drafts and referral notes waiting for approval |
| Outreach HQ: follow-ups | Mon-Sat 11:30 | follow-up drafts waiting for approval, replies flagged |
| Outreach HQ: supervisor | daily 20:10 | health report, issues with remedies (read-only: it changes no code or config) |

None of these can send email. Sending happens only in the GitHub `cycle` workflow, and only for messages
approved on the website. To change a time or a run's budget, edit the task in the app.

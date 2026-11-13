# Outreach HQ: rules for any assistant or person working in this repository

Read `HANDOFF.md` first (what this is, decisions made, what is planned), then `config/voice.md` (the email
quality contract). This file is the short list you must not break.

- **Email quality never goes down.** Follow `config/voice.md`. Use only facts in `config/profile.toml`.
  Never loosen `outreach/messages.py:check_draft`, the sending caps, the verified-address rule or the
  do-not-email list to get something through.
- **Emails are sent only after Shlok approves them on the site.** Never send, approve, switch `mode`,
  post, message or log in anywhere for him. Nothing is ever automated on LinkedIn.
- **Beltech never appears in emails or notes.** No pay, CTC or notice period in a message.
- **Never ask for, print or commit a secret** (passwords, App Passwords, tokens, API keys).
- All data reads and writes go through `python3 -m outreach ...`. Never edit `data/` by hand or with git.
  Run pipeline commands one at a time in the foreground; they queue behind a lock.
- **Record every change in the supervisor log** before you finish (a fix, a feature, a repair, a setting):
  `python3 -m outreach log add --by <who> --kind update|fix|debug|note --title "..." --detail "..." [--ref <commit or id>]`
  Plain words, with the specifics. Shlok reads this on the site's Log page.
- Problems go in the issue log (`issue add`, then `issue remedy` with the cause, `issue resolve` once
  verified gone); those reach the supervisor log automatically.
- Work on a branch and open a pull request. Tests must pass: `python3 -m unittest discover -s tests`.
  Python standard library only. Free tiers only, with a cap on anything paid per use.
- Verify before claiming: open the real posting before qualifying a lead, run the command before saying
  it works, and say plainly what you did not test.
- When you finish or start something listed in `HANDOFF.md` section 6, update sections 4 to 6 of that file.
- Site: `web/` (Next.js), deployed by Vercel from `main`.

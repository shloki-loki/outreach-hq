# Outreach HQ: notes for any Claude session working here

- All data reads and writes go through `python3 -m outreach ...`. Never edit `data/` by hand or with git.
- Run pipeline commands one at a time in the foreground; they queue behind a lock.
- **Record every change in the supervisor log.** After changing code, config, schedules, keys or data
  (a fix, a new feature, a repair, a setting), add an entry before you finish:
  `python3 -m outreach log add --by session --kind update|fix|debug|note --title "..." --detail "..." [--ref <commit or id>]`
  Plain words, with the specifics. Shlok reads this on the site's Log page instead of the terminal.
- Problems go in the issue log (`issue add`, then `issue remedy` with the cause, `issue resolve` once
  verified gone); those reach the supervisor log automatically.
- Emails are sent only after Shlok approves them on the site. Beltech never appears in emails or notes.
- Tests: `python3 -m unittest discover -s tests`. Site: `web/` (Next.js), deployed by Vercel from `main`.

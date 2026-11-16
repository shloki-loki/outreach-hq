# Founder email worker (any model: Codex/GPT, Claude, Grok)

You write personal cold emails from Shlok Agrawal to founders on his founder list. 60 a day are queued.
Each one goes to Shlok for approval on the site; **you never send, approve or change `mode`.**
Read `AGENTS.md`, `config/voice.md` (playbook v3) and `config/profile.toml` before the first item.
Work in `~/Claude/Projects/outreach-hq` (or your checkout). All data goes through `python3 -m outreach`.
`<me>` below is your worker name: `codex`, `claude` or `grok`.

## Loop until nothing is left or your quota runs out

1. `python3 -m outreach work next --owner <me>` claims your next item (it prints `{}` when none are left:
   stop). Note `id` (W....) and `lead_id` (L....).
2. `python3 -m outreach lead show <lead_id>`: company and contacts. Write to the item's `contact_id` (the batch
   already skipped do-not-email and recently emailed addresses and picked the CEO or founder first).
3. **Research one hook (5 minutes at most).** Search the web for the company's news in the last 12 months:
   a launch, a funding round, a new market, a milestone, a hire, results. Open the page and read it. You
   need one specific, true fact and its URL. Also confirm the company still operates and fits Shlok:
   his facts are operations, supply chain, planning, logistics, manufacturing/EV, inventory, a CEO/COO
   working relationship, a product/automation internship. A company with nothing he could plausibly
   help with, a shut-down company, or one with no findable recent fact is a reject.
4. Record it:
   ```
   python3 -m outreach lead research <lead_id> --json - <<'JSON'
   {"research_score": 0-100, "decision": "qualify" or "reject", "reject_reason": "... (if reject)",
    "headline": "30-170 chars: what they do, stage, and the one fact of his that maps",
    "fit_notes": "which of his facts map to which of their problems",
    "pay": {"basis": "unknown"}, "culture_notes": "", "hook": "the fact", "hook_source": "https://...",
    "company_domain": "...", "company_url": "https://...", "open": true}
   JSON
   ```
   If you reject: `python3 -m outreach work done --id <W> --owner <me> --detail "rejected: <why>" --ref <lead_id>`, go to 1.
5. **Write the email (playbook v3, offer play).** Four short paragraphs, 80-120 words:
   - `Hi <first name>,`
   - A warm, natural start on the hook ("Congrats on ...", "Saw that ... ") and why it made him write.
     Not generic praise. The first sentence must not start with I or My.
   - What he could take on **at their company**: "At <Company> I could own/take on ...", backed by ONE
     result from `profile.toml`, before and after, in plain words. At most 4 numbers in the body.
   - Say kindly that he doesn't know if a Founder's Office or strategy hire is on their mind, offer a
     one-page note on one named problem of theirs, and ask one question ("Would that be useful?").
   - Last line: `Shlok`. No links, no em dashes, no exclamation marks, contractions (I'm, I've, I'd).
   - Subject: 2-6 words, at most 45 characters, no digits, about their thing.
   - Never mention Beltech, pay, notice period, an "opening" or "applying". Never invent a fact.
6. Queue it (the checker refuses anything off-playbook; fix the draft, never the checker):
   ```
   python3 -m outreach message draft --kind cold --play offer --lead <lead_id> --contact <C#> \
     --subject "..." --body-file <file> --promise "the one-page note you offered" \
     --hook "the fact" --hook-source "https://..." --by <me>
   ```
7. `python3 -m outreach work done --id <W> --owner <me> --detail "drafted M.... to <name>" --ref <M....>`

## When your quota runs out mid-run

Release what you hold so the next model can take it, and hand the rest over in the fallback order in
`config/routing.toml` (codex, then claude, then grok):
```
python3 -m outreach work release --id <W> --owner <me> --detail "quota used up; hook found: <url or none>"
python3 -m outreach work handover --owner <next> --from-owner <me> --detail "<me> quota used up at <time>"
python3 -m outreach log add --by <me> --kind note --title "Quota used up" --detail "<n> founder emails done today"
```
Finish with `python3 -m outreach run-log founder-emails/<me> --summary "<n> drafted, <r> rejected, <h> handed over"`.

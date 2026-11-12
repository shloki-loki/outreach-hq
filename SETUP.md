# Setup: the steps only you can do

Everything else is built. These need your own logins, so they are yours. About 25 minutes in total.
Run commands from `~/Claude/Projects/outreach-hq`.

## 1. Gmail App Password (lets the system send approved emails and read replies) — 5 min

1. Turn on 2-Step Verification for 111shlokagrawal@gmail.com if it is off.
2. Open https://myaccount.google.com/apppasswords, create one named "Outreach HQ", copy the 16 characters.
3. Give it to GitHub (each command asks you to paste the value; it is stored encrypted):

```bash
gh secret set GMAIL_ADDRESS --repo shloki-loki/outreach-hq
```

```bash
gh secret set GMAIL_APP_PASSWORD --repo shloki-loki/outreach-hq
```

4. For local runs, copy `.env.example` to `.env` and put the same two values there.
5. Prove it works (sends one email to yourself, nothing else):

```bash
python3 -m outreach mail-test
```

## 2. Put the website on Vercel — 10 min

1. https://vercel.com/new → import `shloki-loki/outreach-hq`.
2. Set **Root Directory** to `web`. Framework: Next.js (detected).
3. Create a GitHub token for the site: https://github.com/settings/personal-access-tokens/new →
   "Only select repositories": `outreach-hq` → Repository permissions: **Contents: Read and write**,
   **Actions: Read and write**. Copy it.
4. In the Vercel project, Settings → Environment Variables (Production), add:

| Name | Value |
|---|---|
| `SITE_PASSWORD` | a long password you choose; you type it to open the site |
| `GITHUB_TOKEN` | the token from step 3 |
| `GITHUB_REPO` | `shloki-loki/outreach-hq` |
| `DATA_BRANCH` | `data` |

5. Deploy. Open the site, sign in, check the Leads page shows your leads.
6. Tell the digest where the site lives (replace the URL):

```bash
gh variable set SITE_URL --repo shloki-loki/outreach-hq --body "https://YOUR-SITE.vercel.app"
```

## 3. Your private details (used only to fill forms) — 3 min

```bash
cp config/profile.local.example.toml config/profile.local.toml
```

Fill in current CTC, expected CTC and notice period. Add your LinkedIn profile URL to
`config/profile.toml` (`linkedin = "..."`).

## 4. LinkedIn connections, for referrals — 5 min now, then a wait

1. LinkedIn → Settings → Data privacy → Get a copy of your data → tick **Connections** → Request archive.
2. LinkedIn emails a download link (usually within 10 minutes to a few hours).
3. Unzip, then:

```bash
python3 -m outreach import-connections ~/Downloads/Connections.csv
```

Every lead whose company matches one of your connections then shows them under
"My LinkedIn connections here". Re-export every few weeks to pick up new connections.

## 5. Free email verifier keys (optional, but this is what keeps bounces low)

Without any key, addresses are honest guesses, and the sender caps guesses at 3 a day. Each free account
below adds real verification. Sign up, copy the API key into `.env`:

- QuickEmailVerification (`QEV_API_KEY`): free daily verifications.
- Hunter (`HUNTER_API_KEY`): free monthly finder and verifier credits.
- Reoon Email Verifier (`REOON_API_KEY`): free daily credits.
- Apollo (`APOLLO_API_KEY`): free plan; its API may refuse lookups on free, and the system will say so.

Check the provider's current free allowance and lower `limit` in `config/settings.toml` if it is smaller
than what is written there.

## 6. Go live

Done on 2026-11-12: `mode = "live"`. To pause all sending, set it back to `"dry_run"`:

1. In `config/settings.toml` change `mode = "live"` to `mode = "dry_run"`.
2. Commit and push that one line. Approved emails are then held until you switch back.

## Check everything

```bash
python3 -m outreach doctor
```

Every line should say OK.

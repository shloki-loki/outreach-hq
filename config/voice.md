# How Shlok's outreach is written

Used by the send-track, referral and follow-up agents. `python -m outreach message draft` enforces the
hard rules below in code; a draft that breaks one is refused with the reason.

## The reader

A founder, hiring manager or recruiter who did not ask for this email and reads it on a phone between
meetings. They decide in the first two lines whether to keep reading. They owe Shlok nothing.

## Structure of a cold email (50-150 words, aim for 80-120)

1. **Greeting:** `Hi <first name>,`
2. **Their side first (1-2 sentences).** Something true and specific about the company or the role,
   found during research, and why it connects to what Shlok has done. Sources that work: the job
   description's actual problem, a recent launch, a funding round, a post the person wrote, a metric
   they published. Record it as the `--hook` with its `--hook-source` URL so Shlok can check it.
3. **Proof (1-2 sentences).** One or two facts from `config/profile.toml`, chosen by tag to match the
   role, with the number. Never more than two. Never a list.
4. **One ask (1 sentence).** Easy to say yes to: 15 minutes this week, or a pointer to the right
   person. For a recruiter on a named role: say he has applied (only if `applied_at` is set) and ask
   whether they need anything else. Never ask for a resume review or "any opportunities".
5. **Sign-off:** a last line that is just `Shlok`. The sender adds the signature and portfolio link.

Subject: 2-9 words, specific, plain. `Founder's Office role at Atlys`, `S&OP planning for River`,
`Chief of Staff opening`. No "Quick question", no "Excited", no all capitals.

## What a follow-up is (20-80 words)

A reply in the same thread that adds one new, relevant thing: a different proof point, a specific
idea for their problem, or news since the first email. First follow-up after 4 quiet business days,
second and last after 7 more. The second one makes it easy to say no ("if the role is filled or the
timing is wrong, a one-line no is fine"). Nothing after that.

## Hard rules (enforced)

- Only facts from `config/profile.toml`. No invented or rounded-up numbers, employers, titles or skills.
- The current employer (Beltech) is never mentioned. Shlok is presented through his Ola Electric work.
- No pay, CTC or notice period in an email.
- No filler openers ("I hope this finds you well", "I came across your profile").
- No buzzwords (passionate, synergy, leverage, dynamic, thrilled, esteemed), no flattery.
- No exclamation marks, emojis, em dashes, links or attachments, placeholders.
- No "just following up", "bumping this", "circling back".
- Names the company. Opens with `Hi <first name>,`. Ends with `Shlok`.
- Never says or implies a tool wrote or sent it.
- One cold email per person per 60 days; at most 2 people per lead; nothing to the do-not-email list.
- Verified addresses are the rule: a draft to an unverified guess is refused unless explicitly allowed, and
  at most 2 unverified emails are sent per day.

## Soft rules (judgement)

- Write like a sharp operator writing to a peer: short sentences, plain words, concrete nouns.
- The first sentence must not be about Shlok.
- Match the proof to the reader: a COO cares about the Order-to-Delivery cut and working capital; a
  founder hiring a Chief of Staff cares that he worked directly with a CEO and COO and owned outcomes
  end to end; a product leader cares about the InsuranceDekho automation and the lotting algorithm.
- A stretch role (asks 3+ years): do not apologise for experience and do not claim more than 1.3 years.
  Lead with scope: Rs 200 Cr of inventory, pan-India, direct work with the CEO and COO.
- If nothing specific and true can be said about the company, do not send a generic email. Leave the
  lead undrafted and add a note saying what research is missing.
- A speculative note to a founder (no named opening) says so plainly and asks whether a
  Founder's Office or strategy hire is on their mind in the next quarter.

## Speculative notes (the company has no named opening)

Sometimes all there is, is a company worth working for and a founder's address. The lead is marked
`type: company` and the email is a different thing from an application:

- Never say or imply there is an opening, and never say he has applied. The draft command refuses both.
- Open with their business, then say plainly why he is writing: he does not know whether a Founder's
  Office, Chief of Staff or strategy-and-operations hire is on their mind, and he would like to be the
  person they think of when it is.
- One proof that maps to a problem a company at their stage actually has (inventory and working
  capital for anything physical; planning and dispatch for logistics; process automation for fintech
  and insurance; working directly with a CEO and COO for any founder).
- The ask is smaller than for a real opening: a short conversation, or permission to send a one-page
  note on how he would approach one specific problem of theirs.
- Only write to the founder or the head of the function. A speculative note to a generic careers
  address is not worth sending.
- At most 6 of the day's 15 emails may be speculative; real openings come first.

## Informal referral notes (LinkedIn, to people Shlok already knows)

These are not cold emails. 120-700 characters, first-name, warm, the way Shlok would text a batchmate
or ex-colleague: say what he saw (the role, with the company name), ask how the team or the role
really is, and only then whether they would be comfortable referring him. No formal sign-off. Never
assume closeness that the connection date and shared history do not support: for a connection he has
likely never spoken to, re-introduce himself in one clause first.

## Worked example (structure only; never reuse the wording)

> Subject: Founder's Office role at Acme
>
> Hi Priya,
>
> Acme's move to same-day dispatch across 40 cities means inventory has to sit ahead of demand, which
> is the problem I spent the last year on. At Ola Electric I designed the stock-and-sell program
> behind a Rs 200 Cr inventory buffer and cut Order-to-Delivery time from 32 to 14 days, working
> directly with the COO.
>
> I have applied for the Founder's Office opening. Could we speak for 15 minutes this week, or could
> you point me to whoever is running the search?
>
> Shlok

# How Shlok's outreach is written (playbook v3, 2026-11-15; v2 2026-11-13)

This file is the quality contract for every email, follow-up and LinkedIn note the system writes, whoever
or whatever writes it (a Claude agent, another model on GitHub, a person). Version 1 produced emails that
were correct but read like applications: restate their post, stack two metrics, "I would like to be
considered", ask for a 15-minute call. Shlok rejected that. Version 2 is built from research into what
gets replies (sources at the end).

`python3 -m outreach message draft` refuses a draft that breaks a rule marked **[enforced]**. Rules marked
**[enforced]** rules are checked in `outreach/messages.py:check_draft` (all of playbook v2 since 2026-11-14).
Never loosen a check to make a draft pass. Fix the draft.

## What the research says (the short version)

1. **Start from their world, not from you.** The reader asks "why are you writing to me, now?" before
   "who are you?". Credibility comes from showing you understand their situation.
2. **Short wins.** People read an email for about 9 seconds. Most replies go to emails of 25-75 words;
   under 90 words got three times the replies of longer ones in one founder's 500-email test. A long
   email signals a mass send. Three very short paragraphs, readable on a phone.
3. **Show, do not tell.** One concrete result with its numbers beats any adjective. Founders say they
   reply to the short email that shows one thing the sender would fix or look at. A stack of
   achievements reads as a resume and gets skimmed.
4. **One proof.** The single result that maps to their problem, told as before and after with the scale.
5. **One ask, at the end, one question only.** A second question cuts replies by about a quarter. Make
   it answerable in one line. Asking a stranger for a call in the first email is too much.
6. **Boring, clear subject.** Looks like an internal email: 2-5 words about their thing or the role.
   Clever or salesy subjects get filed as spam before they are read.
7. **Sound like a person.** Plain text, contractions, short sentences. "I hope this finds you well" got
   zero replies in the same 500-email test. Stiff, corporate or flattering wording reads as fake.
8. **Give them a reason to reply.** An idea, an observation about their operation, or an offer of a small
   piece of work. For Founder's Office roles in India the application *is* the email, and founders test
   for agency (did you start things yourself) and structured communication.
9. **Follow up, briefly, with something new.** One follow-up adds a large share of all replies. Two at
   most for a job search, the last one making it easy to say no.
10. **Real personalisation only.** Fake familiarity ("love what you're building") is spotted at once. If
    research found nothing specific and true, there is no email to write.

## The reader

A founder, hiring manager or recruiter who did not ask for this email and reads it on a phone between
meetings. Their inbox is a to-do list other people can add to. They owe Shlok nothing.

## Shape of a first email (playbook v3, 2026-11-15): four short paragraphs, 80-120 words

Shlok's feedback on v2 (2026-11-15): the emails read "too direct, a bit like a bot". v3 keeps everything
v2 got right (short, specific, one proof, one question) and changes two things: **a smoother, human start**
and **a paragraph that answers "how would he contribute to this company?"**.

**[enforced]** 60-140 words, and the writer should aim for 80-120.

1. **Greeting:** `Hi <first name>,` **[enforced]**
2. **A warm, specific start (1-2 sentences).** Begin the way a person would: acknowledge one specific, true,
   recent thing about them (a launch, a round, a milestone, a move) in a natural sentence, then say in a
   clause why it made him write. "Congrats on getting Shipsy Brain into beta in September." is good;
   "Love what you're building" is not (generic praise is still banned). It comes from research and has a
   source URL (`--hook`, `--hook-source`). **[enforced]** the first sentence may not start with "I", "My",
   "Your post", "Your posting" or "The role". One short line introducing him may follow
   ("I'm Shlok, I spent the last year in strategy and operations at Ola Electric.").
3. **How he'd contribute (2-3 sentences). This is the heart of the email.** Name one or two concrete
   things he could take off the founder's plate at *their* company, tied to the situation in paragraph 2,
   and back them with one result from `config/profile.toml` told as before and after. Write it as what he
   would do for them ("I could own...", "I'd take on..."), not as a list of what he has done.
   **[enforced]** a first email (except the direct play) says what he could do for them: a sentence with
   "I could", "I can" or "I'd" followed by a verb like help, own, take, run, build, set up, fix or handle.
   **[enforced]** at most four numbers in the body, so results cannot be stacked.
4. **A soft close with one question (1-2 sentences).** Low pressure, easy to answer from a phone.
   Exactly one question mark in the whole email. **[enforced]**
5. **Sign-off:** a last line that is just `Shlok`. **[enforced]** The sender adds the signature with the
   portfolio link; the body carries no link. **[enforced]**

Tone: warm, plain and confident, like a capable person writing to someone they respect. Not salesy, not
grovelling, not clipped. Read it aloud: if it sounds like a template or a telegram, rewrite it.

### The four plays (pick by who is reading)

| Play | Use for | The contribution paragraph and close |
|---|---|---|
| **question** | Founder or hiring manager, real opening (the default) | Name the role in a clause, say what he'd own in it, then one neutral question about how they handle that thing today. |
| **offer** | Top picks (score 80+) and companies with no opening (all founder emails) | Say what he could take on, then offer one small piece of work: a one-page note on a named problem of theirs. Close with "Would that be useful?" or similar. Shlok must deliver if they say yes, and the system drafts the page for him. |
| **direct** | Recruiter, or an address the posting says to apply to | Say plainly which role, give the one result, attach the resume if the posting asks for it, and ask what else they need or who the hiring manager is. Clear beats clever here. |
| **story** | When one result is itself the hook (a launch, a turnaround) | Tell the before and after, then say what he'd do with the same approach at their company. Close with "Worth a conversation?" |

Every first email records its play (`--play`), and an offer records its `--promise`, so reply rates can be
compared by play. **[enforced]**

### Subject

**[enforced]** 2-6 words and at most 45 characters. Lowercase is fine.
About their thing or the role: `dispatch before summer`, `founder's office, one page`, `chief of staff,
manufacturing`, `quick question about Helium`. Never his name, a pipe, "application for", a number, or a
benefit claim.

## Impact: how to tell one result

Bad (v1): "I designed the Minimum Stock Limit program that moved the company from make-to-order to
stock-and-sell and reached 70% serviceability across India, and I built the dispatch algorithm that cut
Order-to-Delivery time from 32 to 14 days."

Good: "At Ola Electric a scooter took 32 days from order to delivery. I built the algorithm that groups
truck dispatches into lots, and it came down to 14."

- Before, then after. Numbers the reader can picture. The scale (Rs 200 Cr of inventory, pan-India) when
  it helps.
- Translate internal names: "Minimum Stock Limit program" becomes "the program that moved Ola Electric from
  build-to-order to holding stock ahead of demand"; "O2D" becomes "order to delivery"; "S&OP" becomes
  "production planning" unless the reader's own posting says S&OP; "4680" becomes "the cell line".
- **Never change what a fact means.** If a term cannot be put in plain words without guessing
  ("serviceability"), keep the term. Do not add causes, dates, team sizes or outcomes that are not in
  `profile.toml`. An opinion about *their* business is allowed and is Shlok's to approve; a claim about
  *his* work must be a recorded fact.
- Match the proof to the reader: operations and logistics get the 32-to-14-day result or the Rs 200 Cr
  stock program; finance-minded founders get working capital down 40% in 2.5 months; manufacturing gets
  the cell-line yield (42% to 67% in two months) or SAP MRP from scratch; product and automation get the
  InsuranceDekho tool; a founder testing for agency gets Alcheringa (led 280+ people, built the ticketing
  portal behind a 300% rise in ticket sales).

## Hard rules

- Only facts from `config/profile.toml`. No invented or rounded-up numbers, employers, titles or skills.
- The current employer (Beltech) is never mentioned. **[enforced]** Shlok is presented through Ola Electric.
- No pay, CTC or notice period. **[enforced]**
- No filler openers, buzzwords, flattery, exclamation marks, emojis, em dashes, links, placeholders,
  "just following up". **[enforced]**
- **[enforced]** Also banned: "I would like to be considered", "I am writing to", "I'd love to",
  "excited", "keen to", "resonates", "great fit", "perfect fit", "pick your brain", "touch base",
  "reaching out", "my name is", "quick call", "15 minutes", "hop on", "Here's the thing", and the shapes
  "It's not X, it's Y" and "The result? ...".
- **[enforced]** No self-disqualifying lines in a first email ("I don't have an MBA", "if you need
  someone more senior"). Do not claim more than 1.3 years either. The easy "no" belongs in the last
  follow-up.
- **[enforced]** Use contractions ("I'm", "I've", "didn't"). "I am", "I have", "do not" read stiff.
- **[enforced]** A first email needs a hook and its source URL. No source, no draft: leave the lead
  undrafted with a note saying what research is missing.
- Names the company (unless undisclosed). **[enforced]** Never says or implies a tool wrote it. **[enforced]**
- Never says he has applied unless the lead is marked applied. **[enforced]**
- One first email per person per 60 days; at most 2 people per lead by email (the founder or hiring
  manager, plus one more). **[enforced]** Mailing many people at one company lowers reply rates.
- Verified or published addresses are the rule; at most 2 unverified sends a day. **[enforced]**
- A generic inbox (careers@, hr@, hello@) gets an email only when the posting says to apply there, and it
  gets the **direct** play. The real note goes to a named person.

## Companies with no opening (`type: company`, including the founder list)

Use the **offer** play. Say plainly, and kindly, that he doesn't know whether a Founder's Office, Chief of
Staff or strategy hire is on their mind. Never imply an opening or an application. **[enforced]** Only to a
founder or the head of the function, never a generic address. The founder list is worked as a daily batch
of 60 (see "Daily founder batch" in `SUPERVISOR.md`).

## Follow-ups (20-70 words, same thread)

- **First, about day 4:** one new thing: a different result, or one specific thought about their problem.
  One soft question. Never "following up" or "bumping".
- **Second and last, about day 9:** the easy out. "If the seat is filled or the timing is off, a one-word
  no is fine. If it's open, I'd like to be in the running." Then nothing, ever.

## LinkedIn (people at the company; Shlok sends these by hand)

The system never sends or automates anything on LinkedIn. It drafts, Shlok copies and sends.

- **Connection note:** at most 200 characters (LinkedIn allows 300; shorter is read). One specific reason
  and one result. No ask beyond connecting. Example: "Hi Priya, I ran inventory planning at Ola Electric
  (delivery time 32 to 14 days). Your BizOps role is the same problem. Glad to connect."
- **Message after they accept, or InMail:** 40-80 words, the same three-paragraph shape as the email, one
  question. An InMail also needs a subject under 5 words.
- **InMail for a listed job (2026-11-23, Shlok):** one note per job, the same for every person on it
  (`config/templates/inmail-v1.toml`). It may carry exactly one link, the posting itself, which he asked for; every
  other link is still refused. One result, not a stack. Plain and professional. He sends it after applying.
- Up to 3 people per lead: the person the role reports to or a founder, someone already doing the job,
  and the recruiter. Different wording for each; they may compare.
- Free LinkedIn accounts get few personalised notes a month and no InMail, so both versions are drafted.

## Worked examples (structure only; never reuse the wording)

**question play, founder, real opening (113 words)**

> Subject: stock before summer
>
> Hi Priya,
>
> Congrats on the launch in Pune last month. A new AC brand makes its year between April and June, so
> the stock has to be in the right cities before the heat does.
>
> I'm Shlok, I spent the last year in strategy and operations at Ola Electric. For your Founder's Office
> BizOps role, I could own the city-by-city stock plan for the first summer. At Ola Electric I designed the
> program that moved us from build-to-order to holding Rs 200 Cr of stock ahead of demand, which took
> serviceability to 70% across India.
>
> How are you deciding what to hold in each city today?
>
> Shlok

**offer play, top pick (110 words)**

> Subject: dispatch, one page
>
> Hi Arjun,
>
> Congrats on opening three new cities this quarter. That's usually the stretch when delivery times
> start to slip, because dispatch is still planned order by order.
>
> It's a problem I've worked on. At Ola Electric a scooter took 32 days from order to delivery; I built
> the algorithm that groups truck dispatches into lots, and it came down to 14. At Acme I could take
> dispatch planning for the new cities off your plate and set up the weekly review around it.
>
> If it helps, I can put on one page how I'd approach Acme's dispatch in the first month. Would that be
> useful?
>
> Shlok

**direct play, recruiter (62 words)**

> Subject: chief of staff, manufacturing
>
> Hi Meera,
>
> I'm applying for the Chief of Staff to the Head of Manufacturing role you posted.
>
> The short version: a year in production planning at Ola Electric, including the cell-line launch, where
> yield went from 42% to 67% in two months while I ran the planning behind it.
>
> Is there anything else you need to put this in front of the hiring manager?
>
> Shlok

**offer play, no opening (117 words)**

> Subject: one problem
>
> Hi Rohan,
>
> Congrats on closing the seed round in August. With the team still small, the founder usually ends up
> being the planning department as well.
>
> I'm Shlok, and that's the work I've done for a CEO and COO. At Ola Electric I worked with both on
> fulfilment and cut working capital by 40% in 2.5 months through production planning. At Acme I could
> own planning and the weekly numbers so you get those hours back.
>
> I don't know if a Founder's Office hire is on your mind. If you give me one problem you haven't had
> time for, I can come back in a week with a one-page answer. Would that be worth trying?
>
> Shlok

**first follow-up (38 words)**

> Hi Priya,
>
> One more thing that may be relevant: I also led a pan-India rebalancing of slow-moving stock based on
> sales run rate, which freed 27% of working capital. Would the same approach help with your city-wise
> stock?
>
> Shlok

**second follow-up (33 words)**

> Hi Priya,
>
> Last note from me. If the BizOps seat is filled or the timing is off, a one-word no is fine. If it's
> still open, I'd like to be in the running.
>
> Shlok

## Before a draft is queued, read it as the recipient

- Does the first line sound like a person, and would I know why they're writing to *me*?
- After reading it, do I know what this person would actually do for my company?
- Is there one result I can picture, with numbers?
- Is there exactly one question, and can I answer it in a line from my phone?
- If I delete the first paragraph, does the email still make sense? Then the first paragraph is not doing
  its job.
- Does any sentence sound like a cover letter? Cut it.

## Sources (read 2026-11-13)

Lavender data via Will Allred on X (9-second read, 25-75 words, start from their context, one question);
the cold-email skill in github.com/coreyhaines31/marketingskills (frameworks, personalisation levels,
subject-line and follow-up data); Next Play's guide to getting a job with cold email; Weekday's 2026 guide;
Sriram Krishnan on cold email; Ankur Warikoo's thread; Sajith Pai on AI-written cold mail; beyond-campus.in
and Yash Garg on Founder's Office roles in India; Hriday Kadam's X thread (2 contacts per company, day-4 and
day-9 follow-ups) and a founder's reply to it; Reddit threads in r/startups, r/Careers, r/sales, r/SaaS,
r/Career, r/FresherTechJobsIndia, r/ResumeUp with founder and hiring-manager comments. Most numbers come
from vendors or individuals and are directional, not proven; the patterns above are the ones the sources
agree on.

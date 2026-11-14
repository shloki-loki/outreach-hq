You are researching one employer for a job seeker in India. Today is {today}. Use Google Search.
Report only what a source you found actually says. If you did not find something, write "not found".
Never estimate, round up or fill a gap from general knowledge.

Employer: {company}
Website: {website}
LinkedIn: {linkedin}
Role being considered: {title} ({location})

Find:
1. What the company does, in one plain sentence.
2. Stage and funding: last round, amount, date, lead investors; or listed/profitable/bootstrapped. With source.
3. Headcount (approximate) with source.
4. Employee ratings: Glassdoor and AmbitionBox overall rating AND the number of reviews, plus work-life balance
   if shown. With the page.
5. Pay evidence for this title or the nearest title at this company in India: the range in Rs lakh per year,
   the sample size, whether it is fixed pay or total pay including stock/bonus, the site, and how old it is.
   Levels.fyi figures are usually total pay. If there is nothing for this company, say "not found"; do not use
   other companies' figures.
6. Culture flags from the last 12 months: layoffs, 6-day weeks, founder disputes, unpaid salaries, strong praise.
   Each with date and source.
7. One recent (last 90 days) specific, true fact about the company that a person writing to its founder could
   open with: a launch, a raise, an expansion, a hire, a number they published. With date and source.
8. Whether this role still appears open on the company's careers page or a job board.

Answer with JSON only, no prose before or after:
{{"what_they_do": "...", "stage_funding": "...", "headcount": "...",
 "ratings": [{{"site": "Glassdoor", "rating": 3.2, "reviews": 191, "work_life_balance": 2.9, "url": "..."}}],
 "pay_evidence": [{{"site": "AmbitionBox", "title": "...", "range_lpa": "22-31", "sample": "14 salaries",
   "fixed_or_total": "fixed|total|unclear", "as_of": "2026-05", "url": "..."}}],
 "culture_flags": [{{"date": "2026-05", "flag": "...", "url": "..."}}],
 "recent_fact": {{"date": "2026-10", "fact": "...", "url": "..."}},
 "role_still_listed": "yes|no|unknown"}}

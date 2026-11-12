"""Job sources. Each module exposes `fetch(targeting, companies) -> (jobs, errors)`.

A job is a plain dict:
    source, source_id, url, apply_url, company, title, location, posted_at (ISO or None),
    description (plain text), pay_text, experience_text, company_url, contacts (optional list)

Sources here need no login and no key. Sites behind a captcha or login (Naukri, Wellfound,
Hiring Cafe, LinkedIn posts) are worked by the lead-scout agent with its own tools and added
through `python -m outreach lead add`.
"""

from . import ashby, greenhouse, instahyre, lever, linkedin, yc

ALL = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "linkedin": linkedin,
    "instahyre": instahyre,
    "yc": yc,
}

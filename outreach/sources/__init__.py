"""Job sources. Each module exposes `fetch(targeting, companies) -> (jobs, errors)`.

A job is a plain dict:
    source, source_id, url, apply_url, company, title, location, posted_at (ISO or None),
    description (plain text), pay_text, experience_text, company_url, contacts (optional list)

The first six need no login and no key. Naukri, Wellfound and Hiring Cafe block plain requests and are
read through Apify actors (sources/apify.py), only when APIFY_TOKEN is set and inside a monthly cap.
LinkedIn hiring posts are still worked by the lead-scout agent and added with `lead add`.
"""

from . import apify, ashby, greenhouse, instahyre, lever, linkedin, yc

ALL = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "linkedin": linkedin,
    "instahyre": instahyre,
    "yc": yc,
    "naukri": apify.naukri,
    "wellfound": apify.wellfound,
    "hiringcafe": apify.hiringcafe,
}

PAID = ("naukri", "wellfound", "hiringcafe")  # skipped quietly when not set up or not due

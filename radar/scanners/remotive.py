"""Remotive - curated remote-job board (keyless JSON API).

location_filter matches the posting's candidate_required_location - keep only
roles open to the applicant's region (Worldwide / Europe / EMEA / ...), not
"USA only".
"""
import time

from . import (DETAIL_FETCH_DELAY, REMOTE_LOCATIONS, _keeps, clean_text, endpoint,
               fetch, make_job, register)
from ..db import save


@register("remotive")
def scan(s):
    location_filter = [x.lower() for x in s.get("location_filter", REMOTE_LOCATIONS)]
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    base = endpoint("remotive", s)
    seen, saved = set(), 0
    for category in s.get("categories") or [None]:
        url = f"{base}?category={category}" if category else base
        try:
            jobs_data = fetch(url).json().get("jobs", [])
        except Exception as e:
            print("WARN", s["name"], category, e)
            continue
        for job in jobs_data:
            link = job.get("url") or ""
            if link in seen:
                continue
            if not _keeps(job.get("candidate_required_location", ""), location_filter):
                continue
            if not _keeps(job.get("title", ""), title_filter):
                continue
            seen.add(link)
            save(make_job(
                title=(job.get("title") or "").strip(), company=job.get("company_name") or s["name"],
                country=s["country"], location=job.get("candidate_required_location") or "Remote",
                url=link, source=s["name"], description=clean_text(job.get("description", "")),
            ))
            saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved

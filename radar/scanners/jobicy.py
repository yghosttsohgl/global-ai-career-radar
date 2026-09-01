"""Jobicy - curated remote-job board (keyless JSON API).

`jobGeo` gives real region eligibility (Anywhere / Europe / USA / ...), so
location_filter works here. `count` is how many recent jobs to pull.
"""
from . import (REMOTE_LOCATIONS, _keeps, clean_text, endpoint, fetch, make_job,
               register)
from ..db import save


@register("jobicy")
def scan(s):
    location_filter = [x.lower() for x in s.get("location_filter", REMOTE_LOCATIONS)]
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    jobs_data = fetch(endpoint("jobicy", s, count=s.get("count", 100))).json().get("jobs", [])

    seen, saved = set(), 0
    for job in jobs_data:
        title = job.get("jobTitle") or ""
        link = job.get("url") or ""
        geo = job.get("jobGeo") or ""
        if link in seen or not _keeps(geo, location_filter) or not _keeps(title, title_filter):
            continue
        seen.add(link)
        save(make_job(
            title=title.strip(), company=job.get("companyName") or s["name"],
            country=s["country"], location=geo or "Remote",
            url=link, source=s["name"],
            description=clean_text(job.get("jobDescription") or job.get("jobExcerpt") or ""),
        ))
        saved += 1
    return saved

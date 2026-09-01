"""Himalayas - remote-job API (keyless, date-sorted, 20/page).

~100k jobs, mostly US, so we page through the most recent `max_pages` and keep
the region-eligible tech/ops roles.
"""
import time
from datetime import datetime, timezone

from . import (DETAIL_FETCH_DELAY, REMOTE_LOCATIONS, _keeps, clean_text, endpoint,
               fetch, make_job, register)
from ..db import save


@register("himalayas")
def scan(s):
    location_filter = [x.lower() for x in s.get("location_filter", REMOTE_LOCATIONS)]
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    now = datetime.now(timezone.utc).timestamp()
    seen, saved = set(), 0
    for page in range(s.get("max_pages", 25)):
        try:
            jobs_data = fetch(endpoint("himalayas", s, offset=page * 20)).json().get("jobs", [])
        except Exception as e:
            print("WARN", s["name"], f"page {page}", e)
            break
        if not jobs_data:
            break
        for job in jobs_data:
            link = job.get("applicationLink") or ""
            regions = " ".join(job.get("locationRestrictions") or []) or "worldwide"
            if link in seen or not _keeps(regions, location_filter) or not _keeps(job.get("title", ""), title_filter):
                continue
            try:
                if job.get("expiryDate") and float(job["expiryDate"]) < now:
                    continue
            except (TypeError, ValueError):
                pass
            seen.add(link)
            save(make_job(
                title=(job.get("title") or "").strip(), company=job.get("companyName") or s["name"],
                country=s["country"], location=regions,
                url=link, source=s["name"], description=clean_text(job.get("description", "")),
            ))
            saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved

"""JSearch (RapidAPI) - wraps Google for Jobs -> Indeed / LinkedIn / Glassdoor.

Needs RAPIDAPI_KEY (free account, no website); skipped with a warning if unset.
Free tier is ~200 req/mo, so keep the query list short. Scrapes live and is
slow (~7s), hence the 45s timeout.
"""
import os
import time

import requests

from . import DETAIL_FETCH_DELAY, _keeps, endpoint, make_job, register
from ..db import save


@register("jsearch")
def scan(s):
    key = (os.environ.get("RAPIDAPI_KEY") or "").strip()
    if not key:
        print("WARN", s["name"], "RAPIDAPI_KEY not set, skipping")
        return 0
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    host = s.get("rapidapi_host", "jsearch.p.rapidapi.com")
    headers = {"x-rapidapi-key": key, "x-rapidapi-host": host}
    url = endpoint("jsearch", s, host=host)
    seen, saved = set(), 0
    for query in s["queries"]:
        params = {
            "query": query, "country": s["jsearch_country"],
            "date_posted": s.get("date_posted", "month"),
        }
        try:
            # /search-v2 (cursor-paginated) - the old /search 404s on current JSearch.
            r = requests.get(url, params=params, headers=headers, timeout=45)
            data = r.json()
        except Exception as e:
            print("WARN", s["name"], query, e)
            continue
        if data.get("status") != "OK":
            msg = data.get("error") or data.get("message") or data
            if "does not exist" in str(msg) or "not subscribed" in str(msg):
                msg = (f"HTTP {r.status_code}: {msg}  (RapidAPI key not subscribed to JSearch, "
                       f"or wrong endpoint)")
            print("WARN", s["name"], query, msg)
            continue
        for job in (data.get("data") or {}).get("jobs", []):
            link = job.get("job_apply_link") or job.get("job_google_link") or ""
            title = job.get("job_title") or ""
            if link in seen or not _keeps(title, title_filter):
                continue
            seen.add(link)
            loc = ", ".join(filter(None, [job.get("job_city"), job.get("job_state"), job.get("job_country")]))
            save(make_job(
                title=title.strip(), company=job.get("employer_name") or s["name"],
                country=s["country"], location=loc or s.get("location", ""),
                url=link, source=s["name"],
                description=(job.get("job_description") or "")[:6000],
            ))
            saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved

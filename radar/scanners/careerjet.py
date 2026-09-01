"""Careerjet - aggregator API (v4).

Needs CAREERJET_API_KEY; skipped with a warning if unset. The Publisher
program requires a public website that displays their listings, so the
careerjet sources ship `enabled: false`.
"""
import os
import time

import requests

from . import DETAIL_FETCH_DELAY, HEADERS, TIMEOUT, _keeps, clean_text, endpoint, make_job, register
from ..db import save


@register("careerjet")
def scan(s):
    api_key = os.environ.get("CAREERJET_API_KEY")
    if not api_key:
        print("WARN", s["name"], "CAREERJET_API_KEY not set, skipping")
        return 0
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    seen, saved = set(), 0
    for query in s.get("queries") or [s.get("keywords", "")]:
        params = {
            "locale_code": s["locale_code"], "keywords": query, "location": s.get("location", ""),
            "page": 1, "page_size": 100, "sort": "date",
            # Careerjet v4 requires these even for server-side use.
            "user_ip": os.environ.get("CAREERJET_USER_IP", "8.8.8.8"),
            "user_agent": HEADERS["User-Agent"],
        }
        try:
            data = requests.get(endpoint("careerjet", s), params=params,
                                auth=(api_key, ""), headers=HEADERS, timeout=TIMEOUT).json()
        except Exception as e:
            print("WARN", s["name"], query, e)
            continue
        if data.get("type") != "JOBS":
            print("WARN", s["name"], query, data.get("message", data.get("type")))
            continue
        for job in data.get("jobs", []):
            url = job.get("url") or ""
            if url in seen or not _keeps(job.get("title", ""), title_filter):
                continue
            seen.add(url)
            save(make_job(
                title=(job.get("title") or "").strip(), company=job.get("company") or s["name"],
                country=s["country"], location=job.get("locations") or s.get("location", ""),
                url=url, source=s["name"], description=clean_text(job.get("description", "")),
            ))
            saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved

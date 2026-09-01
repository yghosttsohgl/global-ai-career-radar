"""Adzuna - aggregator API (Indeed AT, StepStone, CareerBuilder, ...).

Needs free ADZUNA_APP_ID + ADZUNA_APP_KEY (https://developer.adzuna.com);
skipped with a warning if unset. Austria only - no Japan endpoint.
"""
import os
import time

import requests

from . import DETAIL_FETCH_DELAY, HEADERS, TIMEOUT, _keeps, endpoint, make_job, register
from ..db import save


@register("adzuna")
def scan(s):
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("WARN", s["name"], "ADZUNA_APP_ID/ADZUNA_APP_KEY not set, skipping")
        return 0
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    base = endpoint("adzuna", s, country=s["adzuna_country"])
    seen, saved = set(), 0
    for query in s.get("queries") or [s.get("what", "")]:
        params = {
            "app_id": app_id, "app_key": app_key, "results_per_page": 50,
            "what": query, "where": s.get("where", ""),
            "max_days_old": s.get("max_days_old", 30), "content-type": "application/json",
        }
        try:
            results = requests.get(base, params=params, headers=HEADERS, timeout=TIMEOUT).json().get("results", [])
        except Exception as e:
            print("WARN", s["name"], query, e)
            continue
        for job in results:
            url = job.get("redirect_url") or ""
            if url in seen or not _keeps(job.get("title", ""), title_filter):
                continue
            seen.add(url)
            loc = (job.get("location") or {}).get("display_name") or ""
            save(make_job(
                title=job.get("title", "").strip(),
                company=(job.get("company") or {}).get("display_name") or s["name"],
                country=s["country"], location=loc,
                url=url, source=s["name"], description=job.get("description", ""),
            ))
            saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved

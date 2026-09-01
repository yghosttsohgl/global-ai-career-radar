"""Greenhouse-hosted boards (e.g. Anthropic, PayPay, Cohere).

Public API lists a company's whole board with clean per-job
title/location/description - no scraping. Narrow it with location_filter /
title_filter in sources.yaml.
"""
from . import _keeps, clean_text, endpoint, fetch, make_job, register
from ..db import save


@register("greenhouse")
def scan(s):
    location_filter = [x.lower() for x in s.get("location_filter", [])]
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    data = fetch(endpoint("greenhouse", s, board=s["board"])).json()

    saved = 0
    for job in data.get("jobs", []):
        locations = [job.get("location", {}).get("name") or ""]
        locations += [o.get("location") or "" for o in job.get("offices", [])]
        if not _keeps(" | ".join(locations), location_filter) or not _keeps(job["title"], title_filter):
            continue
        save(make_job(
            title=job["title"], company=job.get("company_name", s["name"]),
            country=s["country"], location=" / ".join(filter(None, set(locations))) or "Unknown",
            url=job["absolute_url"], source=s["name"], description=clean_text(job.get("content", "")),
        ))
        saved += 1
    return saved

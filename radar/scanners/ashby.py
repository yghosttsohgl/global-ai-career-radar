"""Ashby-hosted boards (e.g. Cohere, OpenAI, Perplexity).

Public API returns clean per-job title/location/description - like Greenhouse,
no scraping. Narrow with location_filter / title_filter.
"""
from . import _keeps, endpoint, fetch, make_job, register
from ..db import save


@register("ashby")
def scan(s):
    location_filter = [x.lower() for x in s.get("location_filter", [])]
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    data = fetch(endpoint("ashby", s, org=s["board"])).json()

    saved = 0
    for job in data.get("jobs", []):
        locations = [job.get("location") or ""]
        locations += [o.get("location") or "" for o in job.get("secondaryLocations", [])]
        if not _keeps(" | ".join(locations), location_filter) or not _keeps(job["title"], title_filter):
            continue
        description = (job.get("descriptionPlain") or "")[:6000]
        save(make_job(
            title=job["title"], company=s["name"],
            country=s["country"], location=" / ".join(filter(None, dict.fromkeys(locations))) or "Unknown",
            url=job.get("jobUrl") or job.get("applyUrl") or "", source=s["name"], description=description,
        ))
        saved += 1
    return saved

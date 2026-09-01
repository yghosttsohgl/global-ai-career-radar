"""RemoteOK - large remote-job board (keyless JSON API).

The response is a JSON array whose first element is a legal/metadata blob
(no `position`). `location` is unreliable (often the company HQ city), so we
filter on the title only; every listing here is remote by definition.
"""
from . import _keeps, clean_text, endpoint, fetch, make_job, register
from ..db import save


@register("remoteok")
def scan(s):
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    data = fetch(endpoint("remoteok", s)).json()

    seen, saved = set(), 0
    for job in data:
        title = job.get("position") or ""
        if not title:  # the leading metadata element
            continue
        link = job.get("url") or job.get("apply_url") or ""
        if link in seen or not _keeps(title, title_filter):
            continue
        seen.add(link)
        tags = ", ".join(job.get("tags") or [])
        desc = clean_text(job.get("description") or "")
        if tags:
            desc = f"Tags: {tags}. {desc}"
        save(make_job(
            title=title.strip(), company=job.get("company") or s["name"],
            country=s["country"], location=job.get("location") or "Remote",
            url=link, source=s["name"], description=desc,
        ))
        saved += 1
    return saved

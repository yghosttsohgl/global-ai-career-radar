"""We Work Remotely - one of the oldest curated remote boards (category RSS).

Each category has an `.rss` feed; `<region>` carries eligibility ("Anywhere in
the World", "Europe Only", "North America Only", ...) and the `<title>` is
"Company: Position".
"""
import time

from bs4 import BeautifulSoup

from . import (DETAIL_FETCH_DELAY, REMOTE_LOCATIONS, _keeps, clean_text, endpoint,
               fetch, make_job, register)
from ..db import save

_DEFAULT_CATEGORIES = ["remote-programming-jobs", "remote-devops-sysadmin-jobs",
                       "remote-product-jobs", "remote-customer-support-jobs"]


@register("weworkremotely")
def scan(s):
    location_filter = [x.lower() for x in s.get("location_filter", REMOTE_LOCATIONS)]
    title_filter = [x.lower() for x in s.get("title_filter", [])]

    seen, saved = set(), 0
    for category in s.get("categories") or _DEFAULT_CATEGORIES:
        try:
            soup = BeautifulSoup(fetch(endpoint("weworkremotely", s, category=category)).text, "xml")
        except Exception as e:
            print("WARN", s["name"], category, e)
            continue
        for item in soup.find_all("item"):
            raw = (item.find("title").text if item.find("title") else "").strip()
            link = (item.find("link").text if item.find("link") else "").strip()
            region = item.find("region").text if item.find("region") else ""
            if link in seen or not _keeps(region, location_filter) or not _keeps(raw, title_filter):
                continue
            seen.add(link)
            company, sep, title = raw.partition(":")
            title = title.strip() if sep else raw
            save(make_job(
                title=title, company=(company.strip() if sep else s["name"]),
                country=s["country"], location=region or "Remote",
                url=link, source=s["name"],
                description=clean_text(item.find("description").text if item.find("description") else ""),
            ))
            saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved

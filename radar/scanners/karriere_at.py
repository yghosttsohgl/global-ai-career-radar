"""karriere.at - Austria's biggest board (server-rendered, stable CSS classes).

Accepts a single `url:` or a list of `urls:` (one per keyword category, e.g.
/jobs/software-entwicklung/wien). karriere.at keyword pages match loosely, so
an optional `title_filter:` keeps only postings whose title matches. Results
are de-duped by job URL within a run.
"""
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import DETAIL_FETCH_DELAY, DETAIL_FETCH_LIMIT, _keeps, clean_text, fetch, make_job, register
from ..db import save


@register("karriere_at")
def scan(s):
    urls = s.get("urls") or [s["url"]]
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    seen = set()
    saved = 0
    for listing_url in urls:
        try:
            soup = BeautifulSoup(fetch(listing_url).text, "html.parser")
        except Exception as e:
            print("WARN", s["name"], listing_url, e)
            continue
        for item in soup.select(".m-jobsListItem")[:DETAIL_FETCH_LIMIT]:
            title_a = item.select_one(".m-jobsListItem__titleLink")
            if not title_a:
                continue
            url = urljoin(listing_url, title_a["href"])
            title = title_a.get_text(strip=True)
            if url in seen or not _keeps(title, title_filter):
                continue
            seen.add(url)
            company_el = item.select_one(".m-jobsListItem__company")
            company = company_el.get_text(" ", strip=True) if company_el else s["name"]
            location_el = item.select_one(".m-jobsListItem__location")
            location = location_el.get_text(" ", strip=True).rstrip(", ") if location_el else ""

            description = title
            try:
                description = clean_text(fetch(url).text)
            except Exception as e:
                print("WARN", s["name"], url, e)

            save(make_job(
                title=title, company=company, country=s["country"], location=location,
                url=url, source=s["name"], description=description,
            ))
            saved += 1
            time.sleep(DETAIL_FETCH_DELAY)
    return saved

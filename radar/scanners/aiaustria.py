"""aiaustria.com - Notion-based curated list that links out to many ATSs.

External sites vary wildly (a different ATS per company) and some block or
fail, so we fall back to the title-only description gracefully.
"""
import time

from bs4 import BeautifulSoup

from . import DETAIL_FETCH_DELAY, DETAIL_FETCH_LIMIT, clean_text, fetch, make_job, register
from ..db import save


@register("aiaustria")
def scan(s):
    listing = fetch(s["url"])
    soup = BeautifulSoup(listing.text, "html.parser")

    saved = 0
    for item in soup.select(".notion-collection-list__item")[:DETAIL_FETCH_LIMIT]:
        anchor = item.select_one(".notion-collection-list__item-anchor")
        title_el = item.select_one(".notion-property__title")
        if not anchor or not anchor.get("href") or not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        url = anchor["href"]
        props = [p.get_text(" ", strip=True) for p in item.select(".notion-property")]
        location = next((p for p in props if p and p != title), "")

        description = title
        try:
            detail = fetch(url)
            dsoup = BeautifulSoup(detail.text, "html.parser")
            og = dsoup.find("meta", property="og:description")
            description = og["content"] if og and og.get("content") else clean_text(detail.text)
        except Exception as e:
            print("WARN", s["name"], url, e)

        save(make_job(
            title=title, company=s["name"], country=s["country"], location=location,
            url=url, source=s["name"], description=description,
        ))
        saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved

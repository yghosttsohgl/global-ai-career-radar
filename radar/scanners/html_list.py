"""Generic link-pattern scraper (e.g. sakana.ai/careers).

`link_pattern` (a regex on the anchor path) scopes which links on the listing
page are real job postings vs nav/footer. The listing URL is the source's
`url:` in sources.yaml.
"""
import re
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import DETAIL_FETCH_DELAY, DETAIL_FETCH_LIMIT, clean_text, fetch, make_job, register
from ..db import save


@register("html_list")
def scan(s):
    pattern = re.compile(s["link_pattern"])
    listing = fetch(s["url"])
    soup = BeautifulSoup(listing.text, "html.parser")

    links = {}
    for a in soup.find_all("a", href=True):
        if pattern.match(urlparse(a["href"]).path):
            links[urljoin(s["url"], a["href"])] = " ".join(a.get_text(" ", strip=True).split())

    saved = 0
    for url, link_text in list(links.items())[:DETAIL_FETCH_LIMIT]:
        title, description = link_text, link_text
        try:
            detail = fetch(url)
            dsoup = BeautifulSoup(detail.text, "html.parser")
            if dsoup.title and dsoup.title.string:
                title = dsoup.title.string.strip()
            description = clean_text(detail.text)
        except Exception as e:
            print("WARN", s["name"], url, e)

        save(make_job(
            title=title, company=s["name"], country=s["country"],
            location=s.get("location", ""), url=url, source=s["name"], description=description,
        ))
        saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved

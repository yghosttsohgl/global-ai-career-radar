import argparse
import hashlib
import re
import time
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

from .db import init, save, jobs
from .models import Job
from .scoring import evaluate

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobRadar/1.0; +personal use)"}
TIMEOUT = 20
DETAIL_FETCH_LIMIT = 40   # per source, safety cap on individual job-page fetches
DETAIL_FETCH_DELAY = 0.3  # seconds between detail-page fetches, be polite


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def clean_text(html, limit=6000):
    """Strip nav/head/script noise and return the readable body text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "head", "nav", "header", "footer"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)[:limit]


def make_job(*, title, company, country, location, url, source, description):
    fp = hashlib.sha256(f"{source}|{title}|{url}".lower().encode()).hexdigest()[:24]
    j = Job(
        fingerprint=fp, title=title, company=company, country=country,
        location=location, url=url, source=source, description=description,
    )
    evaluate(j)
    return j


# ---------- Greenhouse-hosted boards (e.g. Anthropic) ----------
# Public API: https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
# Gives clean per-job title/location/description - no scraping needed.

def scan_greenhouse(s):
    board = s["board"]
    location_filter = [x.lower() for x in s.get("location_filter", [])]
    data = fetch(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true").json()

    saved = 0
    for job in data.get("jobs", []):
        locations = [job.get("location", {}).get("name") or ""]
        locations += [o.get("location") or "" for o in job.get("offices", [])]
        locations_text = " | ".join(locations).lower()
        if location_filter and not any(loc in locations_text for loc in location_filter):
            continue
        description = clean_text(job.get("content", ""))
        save(make_job(
            title=job["title"], company=job.get("company_name", s["name"]),
            country=s["country"], location=" / ".join(filter(None, set(locations))) or "Unknown",
            url=job["absolute_url"], source=s["name"], description=description,
        ))
        saved += 1
    return saved


# ---------- Generic link-pattern scraper (e.g. Sakana AI careers) ----------
# link_pattern scopes which anchors are real job postings (not nav/footer links).

def scan_html_list(s):
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


# ---------- karriere.at (server-rendered listing with stable CSS classes) ----------

def scan_karriere_at(s):
    listing = fetch(s["url"])
    soup = BeautifulSoup(listing.text, "html.parser")

    saved = 0
    for item in soup.select(".m-jobsListItem")[:DETAIL_FETCH_LIMIT]:
        title_a = item.select_one(".m-jobsListItem__titleLink")
        if not title_a:
            continue
        title = title_a.get_text(strip=True)
        url = urljoin(s["url"], title_a["href"])
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


# ---------- aiaustria.com (Notion-based curated list; links out to many ATSs) ----------

def scan_aiaustria(s):
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

        # External sites vary wildly (different ATS per company) and some will
        # block or fail - fall back to the title-only description gracefully.
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


SCANNERS = {
    "greenhouse": scan_greenhouse,
    "html_list": scan_html_list,
    "karriere_at": scan_karriere_at,
    "aiaustria": scan_aiaustria,
}


def scan():
    init()
    cfg = yaml.safe_load(open("candidate.yaml", encoding="utf8"))
    for s in cfg["sources"]:
        if not s.get("enabled", True):
            print(s["name"], "skipped (disabled)")
            continue
        scanner = SCANNERS.get(s["type"])
        if not scanner:
            print("WARN", s["name"], f"unknown source type '{s.get('type')}'")
            continue
        try:
            count = scanner(s)
            print(s["name"], f"done ({count} jobs)")
        except Exception as e:
            print("WARN", s["name"], e)


def stats():
    init()
    data = jobs()
    by_country, by_rec = {}, {}
    for j in data:
        by_country[j["country"]] = by_country.get(j["country"], 0) + 1
        by_rec[j["recommendation"] or "UNSCORED"] = by_rec.get(j["recommendation"] or "UNSCORED", 0) + 1
    print("Tracked jobs:", len(data))
    print("By country:", by_country)
    print("By recommendation:", by_rec)


def llm_score():
    from .llm_scoring import score_new_jobs
    n = score_new_jobs()
    print(f"LLM-scored {n} job(s).")


def pending():
    """Dump jobs awaiting LLM scoring as JSON - for manual scoring (e.g. by
    Claude Code itself in a chat session) when no ANTHROPIC_API_KEY is set."""
    import json as _json
    from .llm_scoring import pending_jobs
    rows = [dict(r) for r in pending_jobs()]
    print(_json.dumps(rows, indent=2, ensure_ascii=False))


def apply_llm_scores():
    """Read a JSON array of {fingerprint, match_score, verdict, strengths,
    gaps, tailored_bullets, reasoning} from stdin and write them to the DB -
    the write side of manual scoring, matching pending_jobs()'s output."""
    import json as _json
    import sys as _sys
    from .llm_scoring import apply_llm_result
    results = _json.loads(_sys.stdin.read())
    for r in results:
        apply_llm_result(r["fingerprint"], r)
    print(f"Applied {len(results)} LLM score(s).")


def digest():
    from .digest import send_digest
    send_digest()


def run():
    """Full pipeline: scan sources, LLM-score promising jobs, email a digest."""
    scan()
    llm_score()
    digest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["scan", "stats", "llm-score", "pending", "apply-llm-scores", "digest", "run"])
    args = p.parse_args()
    {
        "scan": scan,
        "stats": stats,
        "llm-score": llm_score,
        "pending": pending,
        "apply-llm-scores": apply_llm_scores,
        "digest": digest,
        "run": run,
    }[args.command]()


if __name__ == "__main__":
    main()

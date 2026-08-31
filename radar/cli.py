import argparse
import hashlib
import os
import re
import time
from datetime import datetime, timezone
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


# ---------- Shared filters for API-backed boards (Greenhouse, Ashby) ----------
# Both APIs list a company's whole board, so sources narrow it two ways:
#   location_filter: keep a posting only if an office location matches
#   title_filter:    keep a posting only if its title matches (drops the
#                    finance/HR/sales noise on a big general-purpose board)
# An unset filter means "keep everything".

def _keeps(text, needles):
    return not needles or any(n in text.lower() for n in needles)


# ---------- Greenhouse-hosted boards (e.g. Anthropic) ----------
# Public API: https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
# Gives clean per-job title/location/description - no scraping needed.

def scan_greenhouse(s):
    board = s["board"]
    location_filter = [x.lower() for x in s.get("location_filter", [])]
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    data = fetch(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true").json()

    saved = 0
    for job in data.get("jobs", []):
        locations = [job.get("location", {}).get("name") or ""]
        locations += [o.get("location") or "" for o in job.get("offices", [])]
        if not _keeps(" | ".join(locations), location_filter) or not _keeps(job["title"], title_filter):
            continue
        description = clean_text(job.get("content", ""))
        save(make_job(
            title=job["title"], company=job.get("company_name", s["name"]),
            country=s["country"], location=" / ".join(filter(None, set(locations))) or "Unknown",
            url=job["absolute_url"], source=s["name"], description=description,
        ))
        saved += 1
    return saved


# ---------- Ashby-hosted boards (e.g. Cohere) ----------
# Public API: https://api.ashbyhq.com/posting-api/job-board/{org}
# Returns clean per-job title/location/description - like Greenhouse, no scraping.

def scan_ashby(s):
    org = s["board"]
    location_filter = [x.lower() for x in s.get("location_filter", [])]
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    data = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{org}").json()

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


# ---------- japan-dev.com (English-friendly Japan tech jobs) ----------
# Public JSON API: https://api.japan-dev.com/api/v1/jobs?limit=N
# No per-job description in the API, so we synthesise one from the structured
# fields (company blurb, skills, Japanese-level, remote-level, salary).

JAPANESE_LEVEL_LABELS = {
    "japanese_level_none": "no Japanese required",
    "japanese_level_beginner": "beginner Japanese",
    "japanese_level_conversational": "conversational Japanese",
    "japanese_level_business_level": "business-level Japanese",
    "japanese_level_fluent": "fluent/native Japanese",
}


def scan_japandev(s):
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    jobs_data = fetch("https://api.japan-dev.com/api/v1/jobs?limit=200").json().get("data", [])
    companies = fetch("https://api.japan-dev.com/api/v1/companies").json().get("data", [])
    blurbs = {c["id"]: (c["attributes"].get("description") or "").strip() for c in companies}

    saved = 0
    for row in jobs_data:
        a = row["attributes"]
        if a.get("is_japanese_only") or not _keeps(a["title"], title_filter):
            continue
        company = a.get("company") or {}
        skills = ", ".join(sk["name"] for sk in a.get("skills") or [])
        jp = JAPANESE_LEVEL_LABELS.get(a.get("japanese_level_enum"), a.get("japanese_level") or "unspecified")
        salary = ""
        if a.get("salary_min") and a.get("salary_max"):
            salary = f" Salary: {a['salary_min']:,}-{a['salary_max']:,} JPY."
        description = (
            f"{a['title']} at {company.get('name', 'a company')}. "
            f"{blurbs.get(str(company.get('id')), '')} "
            f"Location: {a.get('location') or 'Japan'}. Japanese level: {jp}. "
            f"Remote: {(a.get('remote_level') or '').replace('remote_level_', '') or 'unspecified'}. "
            f"Skills: {skills or 'n/a'}.{salary}"
        ).strip()
        url = a.get("application_url") or (
            f"https://japan-dev.com/jobs/{company.get('slug')}/{a['slug']}"
            if company.get("slug") else "https://japan-dev.com/jobs"
        )
        save(make_job(
            title=a["title"], company=company.get("name") or s["name"],
            country=s["country"], location=a.get("location") or "Japan",
            url=url, source=s["name"], description=description,
        ))
        saved += 1
    return saved


# ---------- Aggregator APIs (Adzuna, Careerjet, JSearch) ----------
# These licence/aggregate the big boards (Indeed, LinkedIn, StepStone, ...) and
# expose clean JSON. Each needs free credentials via env vars; a source with
# missing credentials is skipped with a warning, like the optional LLM/Gmail
# steps. Register:
#   Adzuna    - https://developer.adzuna.com          (Austria; no Japan endpoint)
#   Careerjet - careerjet.com/partners (needs a website to publish listings on)
#   JSearch   - https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch (no website
#               needed; wraps Google for Jobs -> Indeed + LinkedIn + Glassdoor)

def scan_adzuna(s):
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("WARN", s["name"], "ADZUNA_APP_ID/ADZUNA_APP_KEY not set, skipping")
        return 0
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    base = f"https://api.adzuna.com/v1/api/jobs/{s['adzuna_country']}/search"
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
                title=job.get("title", "").strip(), company=(job.get("company") or {}).get("display_name") or s["name"],
                country=s["country"], location=loc,
                url=url, source=s["name"], description=job.get("description", ""),
            ))
            saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved


def scan_careerjet(s):
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
            data = requests.get("https://search.api.careerjet.net/v4/query", params=params,
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


def scan_jsearch(s):
    key = (os.environ.get("RAPIDAPI_KEY") or "").strip()
    if not key:
        print("WARN", s["name"], "RAPIDAPI_KEY not set, skipping")
        return 0
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    host = s.get("rapidapi_host", "jsearch.p.rapidapi.com")
    headers = {"x-rapidapi-key": key, "x-rapidapi-host": host}
    seen, saved = set(), 0
    for query in s["queries"]:
        params = {
            "query": query, "country": s["jsearch_country"],
            "date_posted": s.get("date_posted", "month"),
        }
        try:
            # /search-v2 (cursor-paginated) - the old /search 404s on current JSearch.
            # JSearch scrapes live and is slow (~7s typical), so allow extra time.
            r = requests.get(f"https://{host}/search-v2", params=params, headers=headers, timeout=45)
            data = r.json()
        except Exception as e:
            print("WARN", s["name"], query, e)
            continue
        if data.get("status") != "OK":
            msg = data.get("error") or data.get("message") or data
            if "does not exist" in str(msg) or "not subscribed" in str(msg):
                msg = (f"HTTP {r.status_code}: {msg}  (RapidAPI key not subscribed to JSearch, "
                       f"or wrong endpoint)")
            print("WARN", s["name"], query, msg)
            continue
        for job in (data.get("data") or {}).get("jobs", []):
            url = job.get("job_apply_link") or job.get("job_google_link") or ""
            title = job.get("job_title") or ""
            if url in seen or not _keeps(title, title_filter):
                continue
            seen.add(url)
            loc = ", ".join(filter(None, [job.get("job_city"), job.get("job_state"), job.get("job_country")]))
            save(make_job(
                title=title.strip(), company=job.get("employer_name") or s["name"],
                country=s["country"], location=loc or s.get("location", ""),
                url=url, source=s["name"],
                description=(job.get("job_description") or "")[:6000],
            ))
            saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved


# ---------- Remotive (curated remote-job board, keyless JSON API) ----------
# https://remotive.com/api/remote-jobs?category={cat}
# location_filter here matches candidate_required_location - keep only roles
# open to the candidate's region (Worldwide / Europe / EMEA / ...), not "USA only".

def scan_remotive(s):
    location_filter = [x.lower() for x in s.get("location_filter",
                       ["worldwide", "anywhere", "europe", "emea", "global", "germany", "austria"])]
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    seen, saved = set(), 0
    for category in s.get("categories") or [None]:
        url = "https://remotive.com/api/remote-jobs"
        if category:
            url += f"?category={category}"
        try:
            jobs_data = fetch(url).json().get("jobs", [])
        except Exception as e:
            print("WARN", s["name"], category, e)
            continue
        for job in jobs_data:
            link = job.get("url") or ""
            if link in seen:
                continue
            if not _keeps(job.get("candidate_required_location", ""), location_filter):
                continue
            if not _keeps(job.get("title", ""), title_filter):
                continue
            seen.add(link)
            save(make_job(
                title=(job.get("title") or "").strip(), company=job.get("company_name") or s["name"],
                country=s["country"], location=job.get("candidate_required_location") or "Remote",
                url=link, source=s["name"], description=clean_text(job.get("description", "")),
            ))
            saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
    return saved


# ---------- Himalayas (remote-job API, keyless, date-sorted, 20/page) ----------
# https://himalayas.app/jobs/api?limit=20&offset=N  - ~100k jobs, mostly US, so
# we page through the most-recent `max_pages` and keep the region-eligible ones.

def scan_himalayas(s):
    location_filter = [x.lower() for x in s.get("location_filter",
                       ["worldwide", "anywhere", "europe", "emea", "global", "germany", "austria"])]
    title_filter = [x.lower() for x in s.get("title_filter", [])]
    now = datetime.now(timezone.utc).timestamp()
    seen, saved = set(), 0
    for page in range(s.get("max_pages", 25)):
        try:
            jobs_data = fetch(f"https://himalayas.app/jobs/api?limit=20&offset={page * 20}").json().get("jobs", [])
        except Exception as e:
            print("WARN", s["name"], f"page {page}", e)
            break
        if not jobs_data:
            break
        for job in jobs_data:
            link = job.get("applicationLink") or ""
            regions = " ".join(job.get("locationRestrictions") or []) or "worldwide"
            if link in seen or not _keeps(regions, location_filter) or not _keeps(job.get("title", ""), title_filter):
                continue
            try:
                if job.get("expiryDate") and float(job["expiryDate"]) < now:
                    continue
            except (TypeError, ValueError):
                pass
            seen.add(link)
            save(make_job(
                title=(job.get("title") or "").strip(), company=job.get("companyName") or s["name"],
                country=s["country"], location=regions,
                url=link, source=s["name"], description=clean_text(job.get("description", "")),
            ))
            saved += 1
        time.sleep(DETAIL_FETCH_DELAY)
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
# Accepts a single `url` or a list of `urls` (one per keyword category, e.g.
# /jobs/software-entwicklung/wien). Results are de-duped by job URL within the
# run so a posting listed under two categories is only stored once.

def scan_karriere_at(s):
    urls = s.get("urls") or [s["url"]]
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
            if url in seen:
                continue
            seen.add(url)
            title = title_a.get_text(strip=True)
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
    "ashby": scan_ashby,
    "japandev": scan_japandev,
    "adzuna": scan_adzuna,
    "careerjet": scan_careerjet,
    "jsearch": scan_jsearch,
    "remotive": scan_remotive,
    "himalayas": scan_himalayas,
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

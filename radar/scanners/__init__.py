"""Job-board scanners - one module per platform, each self-registering.

To add a platform: drop a `radar/scanners/<name>.py` that calls
`@register("<type>")` on a `scan(source_dict) -> int` function, and add a
`<type>:` entry with that source's parameters to sources.yaml. Nothing else
needs to change - this package auto-imports every module in it.

Shared helpers (fetch, clean_text, make_job, _keeps) and the base-URL table
(ENDPOINTS) live here so the per-platform modules stay tiny.
"""
import hashlib
import importlib
import pkgutil

import requests
from bs4 import BeautifulSoup

from ..db import save
from ..models import Job
from ..scoring import evaluate

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobRadar/1.0; +personal use)"}
TIMEOUT = 20
DETAIL_FETCH_LIMIT = 40   # per source, safety cap on individual job-page fetches
DETAIL_FETCH_DELAY = 0.3  # seconds between detail-page fetches, be polite

# Base API URLs, in one place. A source in sources.yaml may override its own
# with an `endpoint:` key (e.g. a regional mirror or a self-hosted proxy).
ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{org}",
    "japandev_jobs": "https://api.japan-dev.com/api/v1/jobs?limit=200",
    "japandev_companies": "https://api.japan-dev.com/api/v1/companies",
    "adzuna": "https://api.adzuna.com/v1/api/jobs/{country}/search",
    "careerjet": "https://search.api.careerjet.net/v4/query",
    "jsearch": "https://{host}/search-v2",
    "remotive": "https://remotive.com/api/remote-jobs",
    "himalayas": "https://himalayas.app/jobs/api?limit=20&offset={offset}",
    "remoteok": "https://remoteok.com/api",
    "jobicy": "https://jobicy.com/api/v2/remote-jobs?count={count}",
    "weworkremotely": "https://weworkremotely.com/categories/{category}.rss",
}

# Default candidate_required_location / region values a remote source keeps -
# roles open to the applicant's region, not "USA only". Override per source
# with `location_filter:` in sources.yaml.
REMOTE_LOCATIONS = ["worldwide", "anywhere", "europe", "emea", "global",
                    "germany", "austria", "apac"]


def endpoint(key, source=None, **fmt):
    """Resolve an endpoint URL: the source's own `endpoint:` if set, else the
    ENDPOINTS default, formatted with **fmt."""
    tmpl = (source or {}).get("endpoint") or ENDPOINTS[key]
    return tmpl.format(**fmt) if fmt else tmpl


def fetch(url, **kw):
    kw.setdefault("headers", HEADERS)
    kw.setdefault("timeout", TIMEOUT)
    r = requests.get(url, **kw)
    r.raise_for_status()
    return r


def clean_text(html, limit=6000):
    """Strip nav/head/script noise and return the readable body text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "head", "nav", "header", "footer"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)[:limit]


def _keeps(text, needles):
    """True if `needles` is empty or any needle is a substring of `text`.
    Used for location_filter / title_filter on board-wide APIs."""
    return not needles or any(n in text.lower() for n in needles)


def make_job(*, title, company, country, location, url, source, description):
    fp = hashlib.sha256(f"{source}|{title}|{url}".lower().encode()).hexdigest()[:24]
    j = Job(
        fingerprint=fp, title=title, company=company, country=country,
        location=location, url=url, source=source, description=description,
    )
    evaluate(j)
    return j


# --- registry --------------------------------------------------------------
SCANNER_REGISTRY = {}


def register(type_name):
    """Decorator: register a scan function under a sources.yaml `type:` value."""
    def deco(fn):
        SCANNER_REGISTRY[type_name] = fn
        return fn
    return deco


def get_scanner(type_name):
    return SCANNER_REGISTRY.get(type_name)


# Import every sibling module so its @register calls run.
for _mod in pkgutil.iter_modules(__path__):
    if not _mod.name.startswith("_"):
        importlib.import_module(f"{__name__}.{_mod.name}")

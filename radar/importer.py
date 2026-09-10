"""Ad-hoc single-job import - from pasted job text or a posting URL.

Used by the dashboard's "Imported" pool. Imported jobs get
``source = "Manual import"`` so they group into their own pool and always
reach the LLM scoring pass regardless of their rule score.
"""
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .models import Job
from .scoring import evaluate

SOURCE = "Manual import"


def import_job(*, title, company="", country="Unknown", description="", url="", location=""):
    """Build and rule-score one manually-entered job. Returns the Job (not saved -
    the caller persists it with radar.db.save)."""
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    company = (company or "").strip()
    url = (url or "").strip()
    raw = f"{company}|{title}|{url}".lower()
    j = Job(
        fingerprint=hashlib.sha256(raw.encode()).hexdigest()[:24],
        title=title,
        company=company or "Unknown",
        country=country or "Unknown",
        location=(location or "").strip(),
        url=url,
        source=SOURCE,
        source_access="manual",
        description=(description or "").strip(),
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )
    evaluate(j)
    return j


def fetch_posting(url):
    """Best-effort ``{title, company, description, url}`` from a job-posting URL.

    Never raises for a bad page - returns whatever could be read, plus an
    ``error`` key when the fetch itself failed. Many big boards (LinkedIn,
    Indeed) block bots or show a login wall; fall back to pasting the text.
    """
    from .scanners import clean_text, fetch  # shared HTTP client + text cleaner

    url = (url or "").strip()
    out = {"title": "", "company": "", "description": "", "url": url}
    try:
        html = fetch(url).text
    except Exception as e:  # noqa: BLE001 - surfaced to the user, not fatal
        out["error"] = str(e)
        return out

    soup = BeautifulSoup(html, "html.parser")

    def meta(*names):
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    out["title"] = meta("og:title", "twitter:title") or (
        soup.title.get_text(strip=True) if soup.title else "")
    out["company"] = meta("og:site_name") or urlparse(url).netloc.replace("www.", "")
    out["description"] = clean_text(html)
    return out

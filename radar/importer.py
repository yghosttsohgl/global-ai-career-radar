"""Ad-hoc single-job import - from pasted job text or a posting URL.

Used by the dashboard's "Imported" pool. Imported jobs get
``source = "Manual import"`` so they group into their own pool and always
reach the LLM scoring pass regardless of their rule score.
"""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .config import scoring as _scoring
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
    out["market"] = guess_market(out["description"], list(_scoring()["markets"]))
    return out


# --- parse a pasted job posting / page --------------------------------------

_CHROME = re.compile(
    r"^(home|jobs?|careers?|open roles?|all jobs|view all|back to (search|jobs|results)|"
    r"search|menu|filters?|sign ?in|log ?in|register|apply( now)?|share|save( job)?|print|"
    r"report (this )?job|follow|we use cookies|accept( all)?( cookies)?|"
    r"cookie (settings|preferences|policy)|manage cookies|skip to (main )?content|"
    r"breadcrumb|posted \d|\d+ (days?|hours?|weeks?|months?) ago|full[- ]time|part[- ]time)$",
    re.I,
)
_MARKET_CUES = {
    "Japan": ("japan", " tokyo", "osaka", "kyoto", "yokohama", "日本", "東京", "大阪", "jlpt", "日本語"),
    "Austria": ("austria", "österreich", "oesterreich", "vienna", " wien", "graz", "linz",
                "salzburg", "innsbruck"),
}
_REMOTE_CUES = ("fully remote", "100% remote", "work from anywhere", "remote-first",
                "anywhere in the world", "globally remote", "remote (global", "worldwide")
_ROLE_WORDS = re.compile(
    r"\b(engineer|manager|developer|designer|analyst|scientist|specialist|lead|architect|"
    r"consultant|director|officer|intern|associate|coordinator|administrator|owner|"
    r"researcher|marketer|recruiter|writer|producer|strategist|verkäufer|entwickler|"
    r"berater|kellner|barista)\b", re.I)
# strings that look like a location or job attribute, not a company name
_LOC_HINT = re.compile(
    r"\b(remote|global|worldwide|hybrid|on-?site|anywhere|emea|apac|europe|"
    r"united states|usa|uk|full[- ]time|part[- ]time)\b|\(", re.I)


def _lines(text):
    out = []
    for raw in (text or "").splitlines():
        s = re.sub(r"[ \t ]+", " ", raw).strip(" \t •·‣▪◦-–—*|>»«")
        if s:
            out.append(s)
    return out


def _is_chrome(s):
    """A nav / breadcrumb / cookie-banner line, not job content."""
    if _CHROME.match(s) or " > " in s or " » " in s:
        return True
    if s.lower().startswith(("http://", "https://", "www.", "home ", "home|", "home>")):
        return True
    words = s.split()  # a short row of Capitalised words with no role word = a nav bar
    return (2 <= len(words) <= 6 and len(s) < 40 and not _ROLE_WORDS.search(s)
            and all(w[:1].isupper() for w in words if w[:1].isalpha()))


def guess_market(text, markets):
    """Best guess at which configured market a posting belongs to."""
    t = (text or "").lower()
    if "Remote" in markets and any(c in t for c in _REMOTE_CUES):
        return "Remote"
    for m in ("Japan", "Austria"):
        if m in markets and any(c in t for c in _MARKET_CUES[m]):
            return m
    if "Remote" in markets and "remote" in t:
        return "Remote"
    return "Remote" if "Remote" in markets else (markets[0] if markets else "Remote")


def _guess_title(lines):
    head = lines[:40]
    # a line that names a role, of sensible length, not chrome
    for s in head:
        if not _is_chrome(s) and _ROLE_WORDS.search(s) \
           and 2 <= len(s.split()) <= 18 and len(s) <= 140:
            return s
    # else the first content-shaped line
    for s in head:
        if _is_chrome(s):
            continue
        n = len(s.split())
        if 2 <= n <= 16 and 6 <= len(s) <= 140 and not s.endswith((":", ".", "?")):
            return s
    return lines[0] if lines else ""


def _guess_company(text, title):
    for sep in (" at ", " — ", " – ", " | ", " @ ", " - ", " · "):
        if sep in title:
            a, b = (p.strip() for p in title.split(sep, 1))
            for role_side, other in ((a, b), (b, a)):
                if (_ROLE_WORDS.search(role_side) and not _ROLE_WORDS.search(other)
                        and not _LOC_HINT.search(other) and 2 <= len(other) <= 50):
                    return other
    for pat in (r"\bAbout ([A-Z][\w&.\-]+(?: [A-Z][\w&.\-]+){0,3})\b",
                r"\bJoin ([A-Z][\w&.\-]+(?: [A-Z][\w&.\-]+){0,3})\b",
                r"^([A-Z][\w&.\-]+(?: [A-Z][\w&.\-]+){0,3}) is (?:a|an|the|building|hiring|"
                r"looking|on a mission)\b"):
        m = re.search(pat, text or "", re.M)
        if m:
            return m.group(1).strip()
    return ""


def parse_posting(text, markets=None):
    """Split pasted job/page text into ``{title, company, description, market}``.

    Heuristic and best-effort - the dashboard prefills the form with this and the
    user corrects it. ``description`` is the whole pasted text, whitespace-tidied.
    """
    markets = markets or list(_scoring()["markets"])
    lines = _lines(text)
    title = _guess_title(lines)
    return {
        "title": title,
        "company": _guess_company(text, title),
        "description": "\n".join(lines),
        "market": guess_market(text, markets),
    }

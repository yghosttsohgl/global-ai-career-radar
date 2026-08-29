import hashlib
from datetime import datetime, timezone
from .models import Job
from .scoring import evaluate


def import_job(title, company, country, location, url, description):
    raw = f"{company}|{title}|{url}|{description[:500]}".lower()
    j = Job(
        fingerprint=hashlib.sha256(raw.encode()).hexdigest()[:24],
        title=title, company=company or "Unknown", country=country,
        location=location, url=url, source="Manual import",
        source_access="manual", description=description,
        first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
    )
    evaluate(j)
    return j

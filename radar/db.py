import sqlite3
from pathlib import Path

DB = Path("data/jobs.sqlite3")

# Columns added after the original schema. Migrated in with ALTER TABLE so
# existing databases pick them up without a manual migration step.
NEW_COLUMNS = [
    ("llm_score", "REAL"),
    ("llm_verdict", "TEXT"),
    ("llm_reasoning", "TEXT"),
    ("llm_tailored_bullets", "TEXT"),
    ("notified_at", "TEXT"),
    # Hand-set in the dashboard; never touched by scan/score, so a rescan or the
    # scheduled DB commit leaves it alone.
    ("application_status", "TEXT"),
]


def con():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    c = con()

    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            fingerprint TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            location TEXT,
            country TEXT,
            url TEXT,
            source TEXT,
            source_access TEXT,
            description TEXT,
            language_requirement TEXT,
            visa_status TEXT,
            work_authorization TEXT,
            first_seen TEXT,
            last_seen TEXT,
            rule_score REAL,
            recommendation TEXT,
            recommended_cv TEXT,
            strengths TEXT,
            gaps TEXT,
            reason TEXT
        )
    """)

    existing_cols = {row["name"] for row in c.execute("PRAGMA table_info(jobs)")}

    for name, coltype in NEW_COLUMNS:
        if name not in existing_cols:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {name} {coltype}")

    c.commit()
    c.close()


def save(j):
    """Insert a job, or update the scan-derived fields on an existing one.

    first_seen and the llm_*/notified_at columns are deliberately left out of
    the UPDATE clause below so a rescan never resets when a job was first
    seen, re-triggers an LLM re-score, or re-sends a notification.
    """
    c = con()

    c.execute("""
        INSERT INTO jobs (
            fingerprint, title, company, location, country, url, source, source_access,
            description, language_requirement, visa_status, work_authorization,
            first_seen, last_seen, rule_score, recommendation, recommended_cv,
            strengths, gaps, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fingerprint) DO UPDATE SET
            title=excluded.title,
            company=excluded.company,
            location=excluded.location,
            country=excluded.country,
            url=excluded.url,
            source=excluded.source,
            source_access=excluded.source_access,
            description=excluded.description,
            language_requirement=excluded.language_requirement,
            visa_status=excluded.visa_status,
            work_authorization=excluded.work_authorization,
            last_seen=excluded.last_seen,
            rule_score=excluded.rule_score,
            recommendation=excluded.recommendation,
            recommended_cv=excluded.recommended_cv,
            strengths=excluded.strengths,
            gaps=excluded.gaps,
            reason=excluded.reason
    """, (
        j.fingerprint,
        j.title,
        j.company,
        j.location,
        j.country,
        j.url,
        j.source,
        j.source_access,
        j.description,
        j.language_requirement,
        j.visa_status,
        j.work_authorization,
        j.first_seen.isoformat(),
        j.last_seen.isoformat(),
        j.rule_score,
        j.recommendation,
        j.recommended_cv,
        "|".join(j.strengths),
        "|".join(j.gaps),
        j.reason,
    ))

    c.commit()
    c.close()


def set_application_status(fingerprint, status):
    """Set (or clear, with a falsy status) a job's hand-tracked application status."""
    c = con()
    c.execute(
        "UPDATE jobs SET application_status = ? WHERE fingerprint = ?",
        (status or None, fingerprint),
    )
    c.commit()
    c.close()


def jobs():
    c = con()

    rows = c.execute("""
        SELECT *
        FROM jobs
        ORDER BY COALESCE(llm_score, rule_score) DESC, last_seen DESC
    """).fetchall()

    c.close()

    return [dict(row) for row in rows]

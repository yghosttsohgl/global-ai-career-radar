"""Manual-import path: import_job builds a rule-scored, tagged Job (no DB write)."""
from radar.importer import SOURCE, import_job


def test_import_job_builds_a_scored_manual_job():
    j = import_job(
        title="AI Evaluation Engineer",
        company="Acme AI",
        country="Remote",
        description="Evaluate LLM outputs. Python, SQL. English working environment.",
        url="https://example.com/jobs/1",
    )
    assert j.source == SOURCE
    assert j.source_access == "manual"
    assert j.country == "Remote"
    assert j.rule_score > 0  # keyword groups matched
    assert j.recommendation in {"APPLY", "CONSIDER", "SKIP"}


def test_import_job_fingerprint_is_stable_and_requires_a_title():
    a = import_job(title="Same Role", company="Co", url="u")
    b = import_job(title="Same Role", company="Co", url="u", description="different body")
    assert a.fingerprint == b.fingerprint

    try:
        import_job(title="   ")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("blank title should raise ValueError")

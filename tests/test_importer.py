"""Manual-import path: import_job builds a rule-scored, tagged Job (no DB write)."""
from radar.importer import SOURCE, _from_jobposting, import_job, parse_posting


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


def test_parse_posting_splits_a_pasted_page():
    blob = (
        "Skip to content\nJobs  Companies  Salaries\n"
        "Home > Engineering > Senior ML Engineer\n"
        "Senior Machine Learning Engineer at Acme Robotics\n"
        "Tokyo, Japan · Full-time\n"
        "About Acme Robotics\nAcme Robotics builds robots.\n"
        "We use cookies. Accept all\n"
    )
    r = parse_posting(blob, ["Japan", "Austria", "Remote", "Vienna"])
    assert set(r) == {"title", "company", "description", "market"}
    assert "Machine Learning Engineer" in r["title"]
    assert r["company"] == "Acme Robotics"
    assert r["market"] == "Japan"
    assert "builds robots" in r["description"]


def test_parse_posting_defaults_to_remote():
    r = parse_posting("Backend Engineer\nWe are a fully remote team.", ["Japan", "Austria", "Remote"])
    assert r["market"] == "Remote"


def test_from_jobposting_reads_schema_org_fields():
    jp = {
        "@type": "JobPosting",
        "title": "Salesforce Consultant (w/m/d)",
        "hiringOrganization": {"name": "Acme GmbH"},
        "jobLocation": {"address": {"addressLocality": "Wien", "addressCountry": "AT"}},
        "description": "<p>Build Salesforce solutions.</p><ul><li>Apex</li></ul>",
    }
    out = _from_jobposting(jp)
    assert out["title"] == "Salesforce Consultant (w/m/d)"
    assert out["company"] == "Acme GmbH"
    assert "Wien" in out["_place"] and "AT" in out["_place"]
    assert "Build Salesforce solutions" in out["description"]
    assert "<p>" not in out["description"]

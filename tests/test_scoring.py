"""Unit tests for the generic rule-scoring helpers in radar/scoring.py.

These exercise only pure functions and an in-memory Job - no database, no
network, no applicant profile - so they stay green regardless of how
profile/scoring.yaml is tuned.
"""
from radar.models import Job
from radar.scoring import (
    evaluate,
    is_senior_title,
    required_years,
    requires_native_language,
)


def test_required_years_reads_the_largest_experience_figure():
    assert required_years("5+ years of experience with Python") == 5
    assert required_years("3 years experience required, 8 years of experience ideal") == 8


def test_required_years_ignores_figures_without_an_experience_word():
    assert required_years("A company with 25 years of market presence") == 0
    assert required_years("") == 0
    assert required_years(None) == 0


def test_is_senior_title():
    assert is_senior_title("Senior Software Engineer")
    assert is_senior_title("Head of Data")
    assert not is_senior_title("Software Engineer")
    assert not is_senior_title("")


def test_requires_native_language():
    # A business/native cue in the text always trips it.
    assert requires_native_language("Remote", "UNKNOWN", "must be a native German speaker")
    # An explicit BUSINESS_OR_HIGHER classification trips it too.
    assert requires_native_language("Remote", "BUSINESS_OR_HIGHER", "")
    # Plain English-friendly text does not.
    assert not requires_native_language("Remote", "UNKNOWN", "English is the working language")


def test_evaluate_runs_the_full_pipeline_and_sets_a_verdict():
    job = Job(
        fingerprint="t1",
        title="QA Engineer",
        company="Example Corp",
        country="Remote",
        description="We need a QA engineer for test automation and manual testing.",
    )
    evaluate(job)

    assert 0 <= job.rule_score <= 100
    assert job.recommendation in {"APPLY", "CONSIDER", "SKIP"}
    assert job.recommended_cv
    assert isinstance(job.strengths, list)

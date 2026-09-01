"""Loads the applicant-specific configuration.

Everything specific to one job seeker is config, not code:

    profile/master_profile.yaml   the CV / background (source of truth)
    profile/cv_versions.yaml      the tailored CV variants
    profile/scoring.yaml          keyword groups, markets, thresholds, penalties
    sources.yaml                  which job boards to scan

`scoring.yaml` is parsed once here and consumed by radar/scoring.py and
radar/llm_scoring.py; `sources.yaml` is read by radar/cli.py's scan().
"""
import functools

import yaml

SCORING_PATH = "profile/scoring.yaml"
PROFILE_PATH = "profile/master_profile.yaml"
SOURCES_PATH = "sources.yaml"


@functools.lru_cache(maxsize=1)
def scoring():
    """The parsed profile/scoring.yaml (cached)."""
    with open(SCORING_PATH, encoding="utf8") as f:
        return yaml.safe_load(f)


@functools.lru_cache(maxsize=1)
def profile():
    """The `profile:` block of profile/master_profile.yaml (cached)."""
    with open(PROFILE_PATH, encoding="utf8") as f:
        return yaml.safe_load(f)["profile"]


def market(country):
    """Config for `country`, falling back to `default_market`."""
    cfg = scoring()
    return cfg["markets"].get(country) or cfg["default_market"]


def sources():
    """The `sources:` list from sources.yaml (which job boards to scan)."""
    with open(SOURCES_PATH, encoding="utf8") as f:
        return yaml.safe_load(f)["sources"]

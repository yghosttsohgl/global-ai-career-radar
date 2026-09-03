"""Sanity checks that the shipped config files parse and have the shape the
engine expects. Guards against a broken edit to scoring.yaml / sources.yaml.
"""
import yaml

from radar import config


def test_scoring_yaml_has_the_core_sections():
    cfg = config.scoring()
    assert isinstance(cfg["candidate_years"], int)
    for key in ("apply", "consider", "llm_floor"):
        assert key in cfg["thresholds"]
    assert cfg["keyword_groups"] and all(
        {"label", "points", "keywords"} <= g.keys() for g in cfg["keyword_groups"]
    )
    assert cfg["markets"]


def test_sources_yaml_parses_and_every_source_names_a_type():
    for src in config.sources():
        assert src.get("name")
        assert src.get("type")


def test_modules_import_cleanly():
    # Import-time side effects (config parsing, registry population) must not raise.
    import radar.cli  # noqa: F401
    import radar.llm_scoring  # noqa: F401
    from radar.scanners import SCANNER_REGISTRY

    assert SCANNER_REGISTRY


def test_readme_example_yaml_is_valid_if_present(tmp_path):
    # If example profiles are shipped for the public repo, they must be loadable.
    import pathlib

    for name in ("profile/master_profile.example.yaml", "profile/cv_versions.example.yaml"):
        p = pathlib.Path(name)
        if p.exists():
            yaml.safe_load(p.read_text(encoding="utf8"))

from pathlib import Path

import pytest

from content_decay_finder.config import AnalysisConfig, ConfigError, load_config_file, parse_section_rule


def test_load_config_file(tmp_path: Path):
    path = tmp_path / "c.toml"
    path.write_text(
        '[analysis]\nrecent_weeks = 6\ndecline_threshold = 0.3\nseasonality = "site"\nsection_depth = 2\n'
        'ignore = ["/tag/"]\nopportunity_min_impressions = 50\n'
        '[analysis.sections]\nGuides = "^/guides/"\n'
    )
    cfg = load_config_file(path)
    assert cfg.recent_weeks == 6 and cfg.decline_threshold == 0.3 and cfg.seasonality == "site"
    assert cfg.section_rules[0].name == "Guides"
    assert cfg.ignore_patterns[0].pattern == "/tag/"
    assert cfg.opportunity_min_impressions == 50.0


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[analysis]\nnope = 1\n", "unknown setting"),
        ("[analysis]\nrecent_weeks = 1.5\n", "integer"),
        ("[analysis]\nrecent_weeks = true\n", "number"),
        ("[analysis]\nseasonality = 3\n", "string"),
        ('[analysis]\nseasonality = "weekly"\n', "seasonality"),
        ("[analysis]\nstrip_query_strings = 1\n", "true or false"),
        ("[analysis]\ntrend_weeks = 2\n", "at least 3"),
        ("[analysis]\ndecline_threshold = 1.5\n", "threshold"),
        ("[analysis]\nopportunity_min_position = 30\n", "opportunity_min_position"),
        ("[analysis]\nopportunity_target_position = 11\n", "target"),
        ("[analysis]\nsection_depth = -1\n", "negative"),
        ("[analysis]\nsections = 1\n", "map names"),
        ('[analysis]\nignore = ["("]\n', "bad ignore"),
        ("[analysis\n", "c.toml"),
    ],
)
def test_bad_config(tmp_path: Path, text, message):
    path = tmp_path / "c.toml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_config_file(path)


def test_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_config_file(tmp_path / "x.toml")


def test_section_rule_parsing():
    rule = parse_section_rule("Docs=^/docs/")
    assert rule.name == "Docs" and rule.pattern.search("/docs/a")
    for bad in ("nope", "=x", "A=(", "A="):
        with pytest.raises(ConfigError):
            parse_section_rule(bad)


def test_defaults_validate():
    AnalysisConfig().validate()
    with pytest.raises(ConfigError):
        AnalysisConfig(recent_weeks=0).validate()

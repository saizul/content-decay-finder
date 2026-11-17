"""Analysis settings, from defaults, an optional TOML file and command-line flags."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from content_decay_finder.redirects import RedirectMap

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib


class ConfigError(ValueError):
    pass


@dataclass
class SectionRule:
    name: str
    pattern: re.Pattern[str]


@dataclass
class AnalysisConfig:
    # windows, in full weeks (Monday to Sunday), counted back from the last complete week
    recent_weeks: int = 4
    baseline_weeks: int = 8
    trend_weeks: int = 16
    # classification
    decline_threshold: float = 0.20  # a 20% drop (after seasonality) counts as decay
    watch_threshold: float = 0.10
    growth_threshold: float = 0.20
    min_baseline_clicks: float = 30.0
    position_drop: float = 1.0  # positions lost before "position" is listed as a cause
    seasonality: str = "auto"  # "auto", "page", "site" or "off"
    min_seasonal_clicks: float = 30.0
    seasonal_clamp: tuple[float, float] = (0.25, 4.0)
    # sections
    section_depth: int = 1
    section_rules: list[SectionRule] = field(default_factory=list)
    # "almost page 1"
    opportunity_min_position: float = 8.0
    opportunity_max_position: float = 20.0
    opportunity_min_impressions: float = 100.0
    opportunity_target_position: int = 3
    # cannibalisation
    cannibal_min_impressions: float = 100.0
    cannibal_min_share: float = 0.10
    cannibal_min_switches: int = 2
    # output limits
    top: int = 50
    strip_query_strings: bool = True
    ignore_patterns: list[re.Pattern[str]] = field(default_factory=list)
    # redirect maps: old URL (or path) -> new URL (or path), from CSV files and/or inline pairs
    redirect_files: list[Path] = field(default_factory=list)
    redirect_pairs: list[tuple[str, str]] = field(default_factory=list)

    def redirect_map(self) -> RedirectMap | None:
        """The redirect map built from ``redirect_files`` and ``redirect_pairs`` (None when both are empty).

        Raises :class:`~content_decay_finder.redirects.RedirectError` for unreadable files, conflicting rules or
        redirect loops.
        """
        if not self.redirect_files and not self.redirect_pairs:
            return None
        from content_decay_finder.redirects import RedirectMap, load_redirects

        rmap = RedirectMap(strip_query=self.strip_query_strings)
        rmap.update(self.redirect_pairs)
        if self.redirect_pairs:
            rmap.sources.append("config")
        return load_redirects(self.redirect_files, into=rmap)

    def validate(self) -> None:
        if min(self.recent_weeks, self.baseline_weeks, self.trend_weeks) < 1:
            raise ConfigError("recent_weeks, baseline_weeks and trend_weeks must be at least 1")
        if self.trend_weeks < 3:
            raise ConfigError("trend_weeks must be at least 3 for a regression")
        if not 0 < self.decline_threshold < 1 or not 0 < self.watch_threshold <= self.decline_threshold:
            raise ConfigError("need 0 < watch_threshold <= decline_threshold < 1")
        if self.seasonality not in ("auto", "page", "site", "off"):
            raise ConfigError("seasonality must be auto, page, site or off")
        if self.opportunity_min_position >= self.opportunity_max_position:
            raise ConfigError("opportunity_min_position must be below opportunity_max_position")
        if not 1 <= self.opportunity_target_position <= 10:
            raise ConfigError("opportunity_target_position must be between 1 and 10")
        if self.section_depth < 0:
            raise ConfigError("section_depth cannot be negative")


def parse_section_rule(text: str) -> SectionRule:
    """``Guides=^/guides/`` -> a named regular expression matched against the URL path."""
    name, sep, pattern = text.partition("=")
    if not sep or not name.strip() or not pattern:
        raise ConfigError(f"section rule must look like NAME=REGEX, got {text!r}")
    try:
        return SectionRule(name.strip(), re.compile(pattern))
    except re.error as exc:
        raise ConfigError(f"bad regular expression in section rule {text!r}: {exc}") from exc


_SIMPLE = {f.name for f in fields(AnalysisConfig)} - {
    "section_rules",
    "ignore_patterns",
    "seasonal_clamp",
    "redirect_files",
    "redirect_pairs",
}


def apply_mapping(cfg: AnalysisConfig, data: dict[str, Any], base_dir: Path | None = None) -> AnalysisConfig:
    """Apply an ``[analysis]`` table. Relative ``redirects_file`` paths are resolved against ``base_dir``."""
    for key, value in data.items():
        if key == "redirects":
            if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
                raise ConfigError("[analysis.redirects] must map old URLs or paths to new ones (strings)")
            cfg.redirect_pairs += list(value.items())
            continue
        if key == "redirects_file":
            values = [value] if isinstance(value, str) else value
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ConfigError("redirects_file must be a path or a list of paths")
            for v in values:
                cfg.redirect_files.append(base_dir / v if base_dir and not Path(v).is_absolute() else Path(v))
            continue
        if key == "sections":
            if not isinstance(value, dict):
                raise ConfigError("[analysis.sections] must map names to regular expressions")
            cfg.section_rules += [parse_section_rule(f"{k}={v}") for k, v in value.items()]
        elif key == "ignore":
            values = [value] if isinstance(value, str) else value
            try:
                cfg.ignore_patterns += [re.compile(v) for v in values]
            except (re.error, TypeError) as exc:
                raise ConfigError(f"bad ignore pattern: {exc}") from exc
        elif key in _SIMPLE:
            current = getattr(cfg, key)
            if isinstance(current, bool):
                if not isinstance(value, bool):
                    raise ConfigError(f"{key} must be true or false")
            elif isinstance(current, (int, float)) and not isinstance(current, bool):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ConfigError(f"{key} must be a number")
                value = type(current)(value) if isinstance(current, float) else value
                if isinstance(current, int) and not isinstance(value, int):
                    raise ConfigError(f"{key} must be an integer")
            elif isinstance(current, str) and not isinstance(value, str):
                raise ConfigError(f"{key} must be a string")
            setattr(cfg, key, value)
        else:
            raise ConfigError(f"unknown setting {key!r}")
    return cfg


def load_config_file(path: Path, cfg: AnalysisConfig | None = None) -> AnalysisConfig:
    cfg = cfg or AnalysisConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    section = data.get("analysis", data)
    if not isinstance(section, dict):
        raise ConfigError("[analysis] must be a table")
    apply_mapping(cfg, section, base_dir=path.parent)
    cfg.validate()
    return cfg

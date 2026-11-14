"""Core data types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Row:
    """One row of Search Console data: a day, a page and optionally a query."""

    date: date
    page: str
    clicks: float
    impressions: float
    position: float | None
    query: str | None = None

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions else 0.0


@dataclass
class Totals:
    """Summed metrics with an impression-weighted average position."""

    clicks: float = 0.0
    impressions: float = 0.0
    position_weight: float = 0.0  # sum(position * impressions)

    def add(self, clicks: float, impressions: float, position: float | None) -> None:
        self.clicks += clicks
        self.impressions += impressions
        if position is not None and impressions:
            self.position_weight += position * impressions

    def merge(self, other: Totals) -> None:
        self.clicks += other.clicks
        self.impressions += other.impressions
        self.position_weight += other.position_weight

    @property
    def position(self) -> float | None:
        return self.position_weight / self.impressions if self.impressions else None

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions else 0.0

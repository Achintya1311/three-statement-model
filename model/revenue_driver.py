"""Day 2: driver-based revenue build — domestic vs. export segments.

Gulf Oil Lubricants India discloses no sales volume (units × price is not
buildable honestly here — see ``research/sources.md``'s Day 2 note) and no
automotive/industrial segment split (Ind AS 108 treats it as a single
"Lubricants" reportable segment). What it *does* disclose every year is a
geographic revenue split, India vs. Outside India, because that disclosure
is mandatory regardless of the single-segment conclusion. That split is this
module's driver: domestic and export revenue are modeled on their own
growth trajectories rather than one blended top-line growth percentage.

``data/<ticker>/segment_revenue.csv`` carries only the sourced
``export_revenue`` column (₹ Lakh, cited in ``research/sources.md``).
Domestic revenue is derived, not stored, as ``total_revenue (from
financials.csv) - export_revenue`` — see this module's docstring in
``research/sources.md`` for why that is the correct construction for the
two years where the segment note's own total is gross of excise duty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from model.historical import HistoricalStatement, load_historical_statements

SEGMENT_REQUIRED_COLUMNS = ["fiscal_year", "export_revenue"]

FISCAL_YEAR_RE = re.compile(r"^FY(\d{4})-(\d{2})$")


@dataclass(frozen=True)
class SegmentRevenue:
    fiscal_year: str
    domestic_revenue: float
    export_revenue: float

    @property
    def total_revenue(self) -> float:
        return self.domestic_revenue + self.export_revenue

    @property
    def export_share(self) -> float:
        return self.export_revenue / self.total_revenue


@dataclass(frozen=True)
class ForecastYear:
    fiscal_year: str
    domestic_revenue: float
    export_revenue: float

    @property
    def total_revenue(self) -> float:
        return self.domestic_revenue + self.export_revenue


def next_fiscal_year(label: str) -> str:
    """``"FY2023-24"`` -> ``"FY2024-25"``."""
    match = FISCAL_YEAR_RE.match(label)
    if not match:
        raise ValueError(f"not a recognized fiscal-year label: {label!r}")
    start = int(match.group(1)) + 1
    return f"FY{start}-{str(start + 1)[-2:]}"


def fiscal_year_span(first: str, last: str) -> int:
    """Whole years between two ``FY####-##`` labels, by start year."""
    first_match, last_match = FISCAL_YEAR_RE.match(first), FISCAL_YEAR_RE.match(last)
    if not first_match or not last_match:
        raise ValueError(f"not a recognized fiscal-year label pair: {first!r}, {last!r}")
    return int(last_match.group(1)) - int(first_match.group(1))


def load_segment_csv(path: str | Path) -> pd.DataFrame:
    """Load ``segment_revenue.csv`` and check its required columns are present."""
    df = pd.read_csv(path, dtype=str)
    missing = [c for c in SEGMENT_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: segment_revenue.csv missing columns: {missing}")
    if df["fiscal_year"].duplicated().any():
        dupes = sorted(df.loc[df["fiscal_year"].duplicated(), "fiscal_year"].unique())
        raise ValueError(f"{path}: duplicate fiscal_year rows: {dupes}")
    return df


def build_segment_revenue(
    statements: list[HistoricalStatement], segment_df: pd.DataFrame
) -> list[SegmentRevenue]:
    """Reconcile sourced export revenue against ingested total revenue.

    Raises ``ValueError`` if the two inputs don't cover the same fiscal
    years, or if any year's export revenue falls outside ``[0,
    total_revenue]`` — either would mean the segment data and the financials
    data have drifted apart, not a result to silently paper over.
    """
    revenue_by_year = {s.fiscal_year: s.income.revenue for s in statements}
    segment_years = set(segment_df["fiscal_year"])
    missing = set(revenue_by_year) - segment_years
    extra = segment_years - set(revenue_by_year)
    if missing or extra:
        raise ValueError(
            f"segment revenue fiscal years don't match financials.csv: "
            f"missing {sorted(missing)}, unexpected {sorted(extra)}"
        )

    segments = []
    for _, row in segment_df.iterrows():
        fiscal_year = row["fiscal_year"]
        export_revenue = float(row["export_revenue"])
        total_revenue = revenue_by_year[fiscal_year]
        if export_revenue < 0 or export_revenue > total_revenue:
            raise ValueError(
                f"{fiscal_year}: export_revenue {export_revenue} is outside "
                f"[0, total_revenue={total_revenue}]"
            )
        domestic_revenue = total_revenue - export_revenue
        segments.append(SegmentRevenue(fiscal_year, domestic_revenue, export_revenue))
    return sorted(segments, key=lambda s: s.fiscal_year)


def load_segment_revenue(financials_path: str | Path, segment_path: str | Path) -> list[SegmentRevenue]:
    """Load, ingest and reconcile both CSVs into one :class:`SegmentRevenue` per fiscal year."""
    statements = load_historical_statements(financials_path)
    segment_df = load_segment_csv(segment_path)
    return build_segment_revenue(statements, segment_df)


def segment_cagr(segments: list[SegmentRevenue], field: str) -> float:
    """CAGR of ``field`` (``"domestic_revenue"``, ``"export_revenue"`` or
    ``"total_revenue"``) from the first to the last fiscal year."""
    first, last = segments[0], segments[-1]
    years = fiscal_year_span(first.fiscal_year, last.fiscal_year)
    if years <= 0:
        raise ValueError("need at least two distinct fiscal years to compute a CAGR")
    first_value, last_value = getattr(first, field), getattr(last, field)
    return (last_value / first_value) ** (1 / years) - 1


def forecast_revenue(
    segments: list[SegmentRevenue],
    n_years: int,
    domestic_growth: float | None = None,
    export_growth: float | None = None,
) -> list[ForecastYear]:
    """Project ``n_years`` of :class:`ForecastYear` beyond the last historical year.

    Each segment compounds at its own growth rate — its own historical CAGR
    by default, or an explicit override — never one blended top-line growth
    percentage applied to total revenue.
    """
    if n_years < 1:
        raise ValueError("n_years must be >= 1")

    d_growth = domestic_growth if domestic_growth is not None else segment_cagr(segments, "domestic_revenue")
    e_growth = export_growth if export_growth is not None else segment_cagr(segments, "export_revenue")

    last = segments[-1]
    fiscal_year = last.fiscal_year
    domestic, export = last.domestic_revenue, last.export_revenue

    forecasts = []
    for _ in range(n_years):
        fiscal_year = next_fiscal_year(fiscal_year)
        domestic *= 1 + d_growth
        export *= 1 + e_growth
        forecasts.append(ForecastYear(fiscal_year, domestic, export))
    return forecasts

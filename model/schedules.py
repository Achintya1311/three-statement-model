"""Day 3: cost structure, D&A, capex and working-capital schedules.

The source data (``data/<ticker>/financials.csv``, see ``research/sources.md``)
has no cost-by-nature breakdown (cost of materials consumed, employee benefit
expense, other expenses — the lines Schedule III would normally itemize) and
no PP&E gross block or accumulated depreciation. Four honest schedules are
built from what the data does have, each expressed as a margin of revenue:

- **Cost structure**: EBITDA margin — the one real quantitative operating-cost
  figure this data supports, since there is no components breakdown to build
  a bottom-up cost structure from.
- **D&A schedule**: D&A as % of *revenue*, not % of capex. D&A/capex swings
  13%-394% across the ten historical years because D&A depreciates an
  accumulating gross block this data doesn't carry, while D&A/revenue drifts
  smoothly from 0.50% to 2.05% over the same years — the far better-behaved
  driver.
- **Capex schedule**: capex as % of revenue. Capex here is genuinely lumpy
  (0.52%-8.10% of revenue year to year, driven by discrete capacity
  expansions, e.g. FY2017-18's 8.10%), flagged as a limitation rather than
  smoothed away.
- **Working-capital schedule**: net working capital as % of revenue.

Every margin defaults to a trailing average of the last few historical years
(overridable individually) — the same override-the-driver pattern Day 2
established for segment growth rates, applied here to a margin instead of a
growth rate because none of these four lines grows smoothly enough for a
single CAGR to mean anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from model.historical import HistoricalStatement
from model.revenue_driver import ForecastYear

DEFAULT_TRAILING_YEARS = 3


@dataclass(frozen=True)
class ScheduleYear:
    fiscal_year: str
    revenue: float
    ebitda: float
    ebitda_margin: float
    depreciation_amortization: float
    da_margin: float
    capex: float
    capex_margin: float
    net_working_capital: float
    nwc_margin: float


def build_schedule(statements: list[HistoricalStatement]) -> list[ScheduleYear]:
    """One :class:`ScheduleYear` per fiscal year, sorted earliest first."""
    years = []
    for s in sorted(statements, key=lambda s: s.fiscal_year):
        revenue = s.income.revenue
        years.append(
            ScheduleYear(
                fiscal_year=s.fiscal_year,
                revenue=revenue,
                ebitda=s.income.ebitda,
                ebitda_margin=s.income.ebitda / revenue,
                depreciation_amortization=s.cash_flow.depreciation_amortization,
                da_margin=s.cash_flow.depreciation_amortization / revenue,
                capex=s.cash_flow.capex,
                capex_margin=s.cash_flow.capex / revenue,
                net_working_capital=s.balance_sheet.net_working_capital,
                nwc_margin=s.balance_sheet.net_working_capital / revenue,
            )
        )
    return years


def trailing_average(values: list[float], n: int = DEFAULT_TRAILING_YEARS) -> float:
    """Mean of the last ``n`` values, or of all of them if fewer are available."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if not values:
        raise ValueError("need at least one historical value")
    window = values[-n:]
    return sum(window) / len(window)


@dataclass(frozen=True)
class ForecastScheduleYear:
    fiscal_year: str
    revenue: float
    ebitda_margin_used: float
    ebitda: float
    da_margin_used: float
    depreciation_amortization: float
    ebit: float
    capex_margin_used: float
    capex: float
    nwc_margin_used: float
    net_working_capital: float
    delta_nwc: float


def forecast_schedule(
    historical: list[ScheduleYear],
    forecast_revenue: list[ForecastYear],
    ebitda_margin: float | None = None,
    da_margin: float | None = None,
    capex_margin: float | None = None,
    nwc_margin: float | None = None,
    trailing_years: int = DEFAULT_TRAILING_YEARS,
) -> list[ForecastScheduleYear]:
    """Project cost/D&A/capex/working-capital schedules onto a revenue forecast.

    ``forecast_revenue`` is the :class:`model.revenue_driver.ForecastYear` list
    Day 2's own ``forecast_revenue`` produces, so a revenue forecast is never
    re-derived here. Each margin not explicitly overridden defaults to the
    trailing ``trailing_years``-year historical average. ``delta_nwc`` is the
    year-over-year change in net working capital (positive = cash tied up),
    measured against the last historical year for the first forecast year and
    against the prior forecast year afterwards.
    """
    if not historical:
        raise ValueError("need at least one historical schedule year")
    if not forecast_revenue:
        raise ValueError("need at least one forecast year")

    used_ebitda_margin = (
        ebitda_margin if ebitda_margin is not None
        else trailing_average([h.ebitda_margin for h in historical], trailing_years)
    )
    used_da_margin = (
        da_margin if da_margin is not None
        else trailing_average([h.da_margin for h in historical], trailing_years)
    )
    used_capex_margin = (
        capex_margin if capex_margin is not None
        else trailing_average([h.capex_margin for h in historical], trailing_years)
    )
    used_nwc_margin = (
        nwc_margin if nwc_margin is not None
        else trailing_average([h.nwc_margin for h in historical], trailing_years)
    )

    prior_nwc = historical[-1].net_working_capital
    forecasts = []
    for fy in forecast_revenue:
        revenue = fy.total_revenue
        ebitda = revenue * used_ebitda_margin
        da = revenue * used_da_margin
        capex = revenue * used_capex_margin
        nwc = revenue * used_nwc_margin
        forecasts.append(
            ForecastScheduleYear(
                fiscal_year=fy.fiscal_year,
                revenue=revenue,
                ebitda_margin_used=used_ebitda_margin,
                ebitda=ebitda,
                da_margin_used=used_da_margin,
                depreciation_amortization=da,
                ebit=ebitda - da,
                capex_margin_used=used_capex_margin,
                capex=capex,
                nwc_margin_used=used_nwc_margin,
                net_working_capital=nwc,
                delta_nwc=nwc - prior_nwc,
            )
        )
        prior_nwc = nwc
    return forecasts

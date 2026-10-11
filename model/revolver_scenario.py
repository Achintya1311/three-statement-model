"""Day 8: the worked "what happens if they draw the revolver in year two"
scenario NEXT_STEPS.md asks for — the standard interview probe on a debt
schedule, answered with the model's own numbers rather than described in
the abstract.

Day 4/5's own Limitations already flagged that the revolver never draws
on this company's real fixture: CFADS comfortably covers scheduled
amortization and interest in every forecast year, so the draw/repay/
cash-sweep path is exercised only by synthetic unit tests. That is still
true here — a real draw needs a real shortfall, and this fixture
doesn't have one — so this module forces the one DAY 4/5 never had: an
EBITDA-margin shock, applied to exactly one forecast year (default: year
2), with every other year left at ``model.linkage.forecast_full_linkage``'s
own real historical defaults.

**How a single-year shock is built without touching ``forecast_full_linkage``'s
signature.** That function accepts one flat override per assumption, applied
to every forecast year alike — correct for "what if growth is always 2pp
lower", wrong for "what if year 2 specifically takes a margin hit". Day 2/3's
own revenue and schedule forecasters only need the *previous* year's output to
project the next one, so this module calls them twice instead of once:
once for the pre-shock years at baseline assumptions, and again for the
shocked years, re-seeded from the pre-shock run's own last year (wrapped as a
:class:`model.schedules.ScheduleYear` so the second call's trailing-average
margins, where not explicitly overridden, resolve against real continuity,
not a restart). The two pieces of :class:`model.schedules.ForecastScheduleYear`
are concatenated and handed to :func:`model.linkage.forecast_linkage_from_cost_forecasts`
— the exact tax/interest circularity loop ``forecast_full_linkage`` itself
runs, extracted for this reason — so the debt schedule, balance check and
every other line are computed exactly as they would be for any other
forecast, not re-implemented.

A shock is applied to a single fiscal year (``shock_duration=1``, default)
or to several consecutive years (e.g. a shock that does not reverse);
either way, every year outside the shocked span runs at the same baseline
``ebitda_margin`` the first, pre-shock year resolved to — so an isolated
one-year shock shows the balance sheet actually recovering once the margin
reverts, not just degrading forever.
"""

from __future__ import annotations

from dataclasses import dataclass

from model.historical import HistoricalStatement
from model.linkage import ForecastLinkageYear, forecast_linkage_from_cost_forecasts
from model.revenue_driver import SegmentRevenue, forecast_revenue
from model.schedules import DEFAULT_TRAILING_YEARS, ScheduleYear, build_schedule, forecast_schedule


@dataclass(frozen=True)
class RevolverScenarioYear:
    fiscal_year: str
    shocked: bool
    """Whether this year used ``shock_ebitda_margin`` rather than the
    baseline margin every other year used."""
    linkage: ForecastLinkageYear


def _as_schedule_year(f) -> ScheduleYear:
    """Wrap a :class:`model.schedules.ForecastScheduleYear` as a
    :class:`model.schedules.ScheduleYear` so it can seed a second
    ``forecast_schedule`` call as if it were "historical" — the real
    numbers that year actually produced, not a re-derivation."""
    return ScheduleYear(
        fiscal_year=f.fiscal_year,
        revenue=f.revenue,
        ebitda=f.ebitda,
        ebitda_margin=f.ebitda_margin_used,
        depreciation_amortization=f.depreciation_amortization,
        da_margin=f.da_margin_used,
        capex=f.capex,
        capex_margin=f.capex_margin_used,
        net_working_capital=f.net_working_capital,
        nwc_margin=f.nwc_margin_used,
    )


def simulate_revolver_draw_scenario(
    statements: list[HistoricalStatement],
    segments: list[SegmentRevenue],
    forecast_years: int,
    shock_year: int,
    shock_ebitda_margin: float,
    shock_duration: int = 1,
    domestic_growth: float | None = None,
    export_growth: float | None = None,
    baseline_ebitda_margin: float | None = None,
    da_margin: float | None = None,
    capex_margin: float | None = None,
    nwc_margin: float | None = None,
    tax_rate: float | None = None,
    dividend_payout: float | None = None,
    amortization_rate: float | None = None,
    revolver_limit: float | None = None,
    interest_rate: float | None = None,
    circular: bool = True,
    trailing_years: int = DEFAULT_TRAILING_YEARS,
) -> list[RevolverScenarioYear]:
    """Project ``forecast_years`` of the full linkage with EBITDA margin
    held at its real baseline every year except ``shock_year`` through
    ``shock_year + shock_duration - 1`` (1-indexed, inclusive), which use
    ``shock_ebitda_margin`` instead.

    Growth, D&A/capex/NWC margins, tax, interest, amortization and dividend
    payout are unchanged from ``forecast_full_linkage``'s own defaults
    unless explicitly overridden here, and apply uniformly to every year —
    this scenario isolates a single-year operating-margin shock, not a
    change in every assumption at once.
    """
    if forecast_years < 1:
        raise ValueError("forecast_years must be >= 1")
    if shock_duration < 1:
        raise ValueError("shock_duration must be >= 1")
    if shock_year < 1 or shock_year + shock_duration - 1 > forecast_years:
        raise ValueError(
            f"shock_year={shock_year} for shock_duration={shock_duration} does not fit "
            f"inside forecast_years={forecast_years}"
        )

    schedule = build_schedule(statements)
    revenue_forecasts = forecast_revenue(
        segments, forecast_years, domestic_growth=domestic_growth, export_growth=export_growth
    )

    shock_start = shock_year - 1  # 0-indexed
    shock_end = shock_start + shock_duration  # exclusive

    cost_forecasts = []
    shocked_flags = []
    historical_for_next = schedule

    if shock_start > 0:
        pre_shock = forecast_schedule(
            historical_for_next,
            revenue_forecasts[:shock_start],
            ebitda_margin=baseline_ebitda_margin,
            da_margin=da_margin,
            capex_margin=capex_margin,
            nwc_margin=nwc_margin,
            trailing_years=trailing_years,
        )
        cost_forecasts.extend(pre_shock)
        shocked_flags.extend([False] * len(pre_shock))
        historical_for_next = [_as_schedule_year(pre_shock[-1])]
        resolved_baseline_margin = pre_shock[-1].ebitda_margin_used
    else:
        resolved_baseline_margin = baseline_ebitda_margin

    shocked = forecast_schedule(
        historical_for_next,
        revenue_forecasts[shock_start:shock_end],
        ebitda_margin=shock_ebitda_margin,
        da_margin=da_margin,
        capex_margin=capex_margin,
        nwc_margin=nwc_margin,
        trailing_years=trailing_years,
    )
    cost_forecasts.extend(shocked)
    shocked_flags.extend([True] * len(shocked))
    historical_for_next = [_as_schedule_year(shocked[-1])]

    if shock_end < forecast_years:
        if resolved_baseline_margin is None:
            # No pre-shock year resolved a baseline (the shock starts in
            # year 1): fall back to the same trailing-historical default
            # forecast_schedule itself would use, derived once from the
            # real historical schedule so post-shock years recover to the
            # true baseline, not the shocked one.
            resolved_baseline_margin = forecast_schedule(
                schedule, revenue_forecasts[shock_end - 1 : shock_end], ebitda_margin=baseline_ebitda_margin
            )[0].ebitda_margin_used
        post_shock = forecast_schedule(
            historical_for_next,
            revenue_forecasts[shock_end:],
            ebitda_margin=resolved_baseline_margin,
            da_margin=da_margin,
            capex_margin=capex_margin,
            nwc_margin=nwc_margin,
            trailing_years=trailing_years,
        )
        cost_forecasts.extend(post_shock)
        shocked_flags.extend([False] * len(post_shock))

    linkage_forecasts = forecast_linkage_from_cost_forecasts(
        statements,
        cost_forecasts,
        tax_rate=tax_rate,
        dividend_payout=dividend_payout,
        amortization_rate=amortization_rate,
        revolver_limit=revolver_limit,
        interest_rate=interest_rate,
        circular=circular,
        trailing_years=trailing_years,
    )

    return [
        RevolverScenarioYear(fiscal_year=l.fiscal_year, shocked=shocked, linkage=l)
        for l, shocked in zip(linkage_forecasts, shocked_flags)
    ]

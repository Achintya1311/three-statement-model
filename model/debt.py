"""Day 4 CLI: debt schedule — mandatory amortization, revolver, cash sweep,
interest on average debt behind an explicit circularity toggle.

    python -m model.debt --ticker GULFOILLUB
    python -m model.debt --ticker GULFOILLUB --forecast-years 3 --no-circular
    python -m model.debt --ticker GULFOILLUB --amort-rate 0.05 --revolver-limit 40000 \\
        --interest-rate 0.07

Loads ``data/<ticker>/financials.csv`` and ``data/<ticker>/segment_revenue.csv``,
chains Day 2's revenue forecast through Day 3's EBITDA/capex/working-capital
schedule, and feeds ``model.debt_schedule`` a pre-tax, pre-interest cash
available for debt service (CFADS) proxy: ``EBITDA - capex - delta_nwc``.

That proxy deliberately excludes cash taxes. Cash tax depends on pretax
income, which is EBIT minus *this schedule's own* interest expense output —
taxing the proxy here would just move the circularity Day 5's full linkage
has to resolve anyway (income statement -> cash taxes -> debt schedule ->
interest -> income statement) into this module without actually resolving
it. Printed and documented as a known simplification, not hidden.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model.debt_schedule import (
    DEFAULT_AMORTIZATION_RATE,
    build_historical_debt_schedule,
    default_interest_rate,
    default_revolver_limit,
    forecast_debt_schedule,
)
from model.historical import load_historical_statements
from model.revenue_driver import forecast_revenue, load_segment_revenue
from model.schedules import DEFAULT_TRAILING_YEARS, build_schedule, forecast_schedule

ROOT = Path(__file__).resolve().parent.parent


def default_financials_path(ticker: str) -> Path:
    return ROOT / "data" / ticker / "financials.csv"


def default_segment_path(ticker: str) -> Path:
    return ROOT / "data" / ticker / "segment_revenue.csv"


def run(
    ticker: str,
    financials_path: Path,
    segment_path: Path,
    forecast_years: int,
    amortization_rate: float | None,
    revolver_limit: float | None,
    interest_rate: float | None,
    circular: bool,
    trailing_years: int,
) -> int:
    if not financials_path.exists():
        print(f"no financials data at {financials_path}", file=sys.stderr)
        return 1
    if not segment_path.exists():
        print(f"no segment revenue data at {segment_path}", file=sys.stderr)
        return 1
    if forecast_years < 1:
        print("--forecast-years must be >= 1 (the debt schedule has nothing to project otherwise)", file=sys.stderr)
        return 1

    try:
        statements = load_historical_statements(financials_path)
        segments = load_segment_revenue(financials_path, segment_path)
    except ValueError as exc:
        print(f"debt schedule build failed: {exc}", file=sys.stderr)
        return 1

    historical_debt = build_historical_debt_schedule(statements)
    used_amort_rate = amortization_rate if amortization_rate is not None else DEFAULT_AMORTIZATION_RATE
    used_revolver_limit = revolver_limit if revolver_limit is not None else default_revolver_limit(historical_debt)
    used_interest_rate = (
        interest_rate if interest_rate is not None else default_interest_rate(historical_debt, trailing_years)
    )

    print(f"{ticker}: {len(historical_debt)} fiscal years of historical debt")
    print(f"{'Fiscal year':<12} {'Total debt':>14} {'Interest exp.':>14} {'Implied rate':>13}")
    for h in historical_debt:
        rate_str = f"{h.implied_interest_rate:>13.2%}" if h.implied_interest_rate is not None else f"{'n/a':>13}"
        print(f"{h.fiscal_year:<12} {h.total_debt:>14,.2f} {h.interest_expense:>14,.2f} {rate_str}")

    schedule = build_schedule(statements)
    revenue_forecasts = forecast_revenue(segments, forecast_years)
    cost_forecasts = forecast_schedule(schedule, revenue_forecasts, trailing_years=trailing_years)
    cfads = [f.ebitda - f.capex - f.delta_nwc for f in cost_forecasts]
    fiscal_years = [f.fiscal_year for f in cost_forecasts]

    debt_forecasts = forecast_debt_schedule(
        historical_debt,
        fiscal_years,
        cfads,
        amortization_rate=amortization_rate,
        revolver_limit=revolver_limit,
        interest_rate=interest_rate,
        circular=circular,
        trailing_years=trailing_years,
    )

    mode = "average-balance, iterative" if circular else "opening-balance, single-pass"
    print(
        f"\nforecast ({forecast_years}y, amort {used_amort_rate:.2%}/yr, "
        f"revolver limit {used_revolver_limit:,.2f}, interest {used_interest_rate:.2%}, {mode}):"
    )
    print(
        f"{'Fiscal year':<12} {'CFADS':>12} {'Amort.':>10} {'Interest':>10} {'Revolver draw':>13} "
        f"{'Revolver pay':>13} {'Ending debt':>13} {'Gap':>10} {'Converged':>9}"
    )
    for f, c in zip(debt_forecasts, cfads):
        print(
            f"{f.fiscal_year:<12} {c:>12,.2f} {f.scheduled_amortization:>10,.2f} {f.interest_expense:>10,.2f} "
            f"{f.revolver_draw:>13,.2f} {f.revolver_repayment:>13,.2f} {f.ending_total_debt:>13,.2f} "
            f"{f.unmet_financing_gap:>10,.2f} {str(f.converged):>9}"
        )

    if any(f.unmet_financing_gap > 0 for f in debt_forecasts):
        print(
            "\nwarning: the revolver limit could not cover every year's cash shortfall "
            "(see 'Gap' above) — this is a real financing gap, not a bug",
            file=sys.stderr,
        )
    if any(not f.converged for f in debt_forecasts):
        print("\nwarning: the circular interest solve did not converge for every year", file=sys.stderr)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", required=True, help="e.g. GULFOILLUB (no yfinance suffix)")
    parser.add_argument("--financials", default=None, help="defaults to data/<ticker>/financials.csv")
    parser.add_argument("--segments", default=None, help="defaults to data/<ticker>/segment_revenue.csv")
    parser.add_argument("--forecast-years", type=int, default=3, help="years to project forward (>= 1)")
    parser.add_argument(
        "--amort-rate", type=float, default=None, help="override mandatory amortization rate, e.g. 0.10"
    )
    parser.add_argument("--revolver-limit", type=float, default=None, help="override revolver facility size")
    parser.add_argument("--interest-rate", type=float, default=None, help="override interest rate, e.g. 0.065")
    parser.add_argument(
        "--trailing-years",
        type=int,
        default=DEFAULT_TRAILING_YEARS,
        help="years of history to average for the default interest rate and Day 3 margins",
    )
    circular_group = parser.add_mutually_exclusive_group()
    circular_group.add_argument(
        "--circular", dest="circular", action="store_true", help="average-balance interest, solved iteratively (default)"
    )
    circular_group.add_argument(
        "--no-circular",
        dest="circular",
        action="store_false",
        help="opening-balance interest, single pass, no iteration",
    )
    parser.set_defaults(circular=True)
    args = parser.parse_args(argv)

    financials_path = Path(args.financials) if args.financials else default_financials_path(args.ticker)
    segment_path = Path(args.segments) if args.segments else default_segment_path(args.ticker)
    return run(
        args.ticker,
        financials_path,
        segment_path,
        args.forecast_years,
        args.amort_rate,
        args.revolver_limit,
        args.interest_rate,
        args.circular,
        args.trailing_years,
    )


if __name__ == "__main__":
    raise SystemExit(main())

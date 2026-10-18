"""Day 8 CLI: the worked "what happens if they draw the revolver in year
two" scenario (``model.revolver_scenario``) — the standard interview probe
on this artifact, answered with real numbers instead of left as an
exercise for the reader.

    python -m model.revolver --ticker GULFOILLUB
    python -m model.revolver --ticker GULFOILLUB --shock-year 2 --shock-ebitda-margin 0.05
    python -m model.revolver --ticker GULFOILLUB --shock-year 2 --shock-duration 3 --forecast-years 4

Every year except the shocked span runs at the real historical defaults
(the same ones ``model.statements`` uses) — see ``model/revolver_scenario.py``'s
module docstring for how a single-year shock is built without changing
``model.linkage.forecast_full_linkage``'s own all-years-alike override
flags.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model.historical import load_historical_statements
from model.linkage import assert_balance_sheet_balances
from model.revenue_driver import load_segment_revenue
from model.revolver_scenario import simulate_revolver_draw_scenario
from model.schedules import DEFAULT_TRAILING_YEARS

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
    shock_year: int,
    shock_duration: int,
    shock_ebitda_margin: float,
    circular: bool,
    trailing_years: int,
) -> int:
    if not financials_path.exists():
        print(f"no financials data at {financials_path}", file=sys.stderr)
        return 1
    if not segment_path.exists():
        print(f"no segment revenue data at {segment_path}", file=sys.stderr)
        return 1

    try:
        statements = load_historical_statements(financials_path)
        segments = load_segment_revenue(financials_path, segment_path)
    except ValueError as exc:
        print(f"revolver scenario build failed: {exc}", file=sys.stderr)
        return 1

    try:
        results = simulate_revolver_draw_scenario(
            statements,
            segments,
            forecast_years,
            shock_year,
            shock_ebitda_margin,
            shock_duration=shock_duration,
            circular=circular,
            trailing_years=trailing_years,
        )
    except ValueError as exc:
        print(f"revolver scenario build failed: {exc}", file=sys.stderr)
        return 1

    shock_span = (
        f"year {shock_year}" if shock_duration == 1 else f"years {shock_year}-{shock_year + shock_duration - 1}"
    )
    mode = "average-balance, iterative" if circular else "opening-balance, single-pass"
    print(
        f"{ticker}: revolver-draw scenario, EBITDA margin shocked to {shock_ebitda_margin:.1%} "
        f"in {shock_span} only ({forecast_years}y forecast, {mode} interest)"
    )
    print(
        f"\n{'Fiscal year':<12}{'Shocked':>9}{'EBITDA':>14}{'Interest':>10}{'Draw':>10}"
        f"{'Repay':>10}{'End debt':>12}{'Gap':>14}{'Balances':>10}"
    )
    for r in results:
        f = r.linkage
        print(
            f"{f.fiscal_year:<12}{str(r.shocked):>9}{f.ebitda:>14,.2f}{f.interest_expense:>10,.2f}"
            f"{f.revolver_draw:>10,.2f}{f.revolver_repayment:>10,.2f}"
            f"{f.ending_total_debt:>12,.2f}{f.unmet_financing_gap:>14,.2f}{str(f.balance_check_passed):>10}"
        )

    if any(r.linkage.unmet_financing_gap > 0 for r in results):
        print(
            "\nwarning: the revolver limit could not cover every year's cash shortfall "
            "(see 'Gap' above) — this is a real financing gap, not a bug",
            file=sys.stderr,
        )

    try:
        assert_balance_sheet_balances([r.linkage for r in results])
    except AssertionError as exc:
        print(f"\nBALANCE CHECK FAILED: {exc}", file=sys.stderr)
        return 1

    print("\nbalance check passed for every forecast year: assets = liabilities + equity")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", required=True, help="e.g. GULFOILLUB (no yfinance suffix)")
    parser.add_argument("--financials", default=None, help="defaults to data/<ticker>/financials.csv")
    parser.add_argument("--segments", default=None, help="defaults to data/<ticker>/segment_revenue.csv")
    parser.add_argument("--forecast-years", type=int, default=4, help="years to project forward (>= 1)")
    parser.add_argument("--shock-year", type=int, default=2, help="1-indexed forecast year the shock starts in")
    parser.add_argument(
        "--shock-duration", type=int, default=1, help="how many consecutive years the shock lasts (default 1)"
    )
    parser.add_argument(
        "--shock-ebitda-margin",
        type=float,
        default=0.05,
        help="EBITDA margin during the shocked year(s), e.g. 0.05 (real historical margin is ~14%%)",
    )
    parser.add_argument(
        "--trailing-years",
        type=int,
        default=DEFAULT_TRAILING_YEARS,
        help="years of history to average for any rate/margin not overridden",
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
        args.shock_year,
        args.shock_duration,
        args.shock_ebitda_margin,
        args.circular,
        args.trailing_years,
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Day 5 CLI: full three-statement linkage, with a balance-check assertion
that fails loudly for every forecast year.

    python -m model.statements --ticker GULFOILLUB
    python -m model.statements --ticker GULFOILLUB --forecast-years 3 --no-circular
    python -m model.statements --ticker GULFOILLUB --tax-rate 0.26 --dividend-payout 0.2

Chains Day 2's revenue forecast, Day 3's EBITDA/D&A/capex/NWC schedule and
Day 4's debt schedule (``model.linkage``) into a full income statement,
cash flow and balance sheet per forecast year, and checks assets =
liabilities + equity for every one of them — exits non-zero, with the
offending years named on stderr, if any year fails to balance.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from model.historical import load_historical_statements
from model.linkage import (
    DEFAULT_BALANCE_TOLERANCE,
    DEFAULT_DIVIDEND_PAYOUT,
    assert_balance_sheet_balances,
    forecast_full_linkage,
    to_fundamentals_contract,
)
from model.revenue_driver import load_segment_revenue
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
    tax_rate: float | None,
    dividend_payout: float | None,
    amortization_rate: float | None,
    revolver_limit: float | None,
    interest_rate: float | None,
    circular: bool,
    trailing_years: int,
    contract_path: Path | None = None,
) -> int:
    if not financials_path.exists():
        print(f"no financials data at {financials_path}", file=sys.stderr)
        return 1
    if not segment_path.exists():
        print(f"no segment revenue data at {segment_path}", file=sys.stderr)
        return 1
    if forecast_years < 1:
        print("--forecast-years must be >= 1 (the linkage has nothing to project otherwise)", file=sys.stderr)
        return 1

    try:
        statements = load_historical_statements(financials_path)
        segments = load_segment_revenue(financials_path, segment_path)
    except ValueError as exc:
        print(f"linkage build failed: {exc}", file=sys.stderr)
        return 1

    forecasts = forecast_full_linkage(
        statements,
        segments,
        forecast_years,
        tax_rate=tax_rate,
        dividend_payout=dividend_payout,
        amortization_rate=amortization_rate,
        revolver_limit=revolver_limit,
        interest_rate=interest_rate,
        circular=circular,
        trailing_years=trailing_years,
    )

    mode = "average-balance, iterative" if circular else "opening-balance, single-pass"
    used_payout = dividend_payout if dividend_payout is not None else DEFAULT_DIVIDEND_PAYOUT
    print(f"{ticker}: full linkage, {forecast_years}y forecast ({mode} interest, {used_payout:.0%} dividend payout)")
    print(
        "Educational research on historical data. Not investment advice. "
        "Not a SEBI-registered research analyst."
    )
    print(
        f"{'Fiscal year':<12} {'Revenue':>14} {'EBIT':>12} {'Interest':>10} {'Tax':>10} {'Net income':>12}"
    )
    for f in forecasts:
        print(
            f"{f.fiscal_year:<12} {f.revenue:>14,.2f} {f.ebit:>12,.2f} {f.interest_expense:>10,.2f} "
            f"{f.tax_expense:>10,.2f} {f.net_income:>12,.2f}"
        )

    print(
        f"\n{'Fiscal year':<12} {'Total assets':>14} {'Debt':>12} {'Equity+other':>14} {'Diff':>10} "
        f"{'Gap':>10} {'Balances':>9} {'Converged':>9}"
    )
    for f in forecasts:
        converged = f.debt_converged and f.tax_converged
        print(
            f"{f.fiscal_year:<12} {f.total_assets:>14,.2f} {f.ending_total_debt:>12,.2f} "
            f"{f.equity_and_other_liabilities:>14,.2f} {f.balance_difference:>10,.4f} "
            f"{f.unmet_financing_gap:>10,.2f} {str(f.balance_check_passed):>9} {str(converged):>9}"
        )

    print(
        f"\n{'Fiscal year':<12} {'Shares out.':>14} {'EPS':>10} {'DPS':>10} {'BVPS':>10}"
    )
    for f in forecasts:
        print(
            f"{f.fiscal_year:<12} {f.shares_outstanding:>14,.0f} {f.eps:>10,.2f} "
            f"{f.dividend_per_share:>10,.2f} {f.book_value_per_share:>10,.2f}"
        )
    print(
        "(shares outstanding held flat at the last historical value -- no corporate "
        "action is modeled; EPS/DPS/BVPS are in rupees, converted from the ₹-lakh "
        "figures above)"
    )

    if any(not (f.debt_converged and f.tax_converged) for f in forecasts):
        print(
            "\nwarning: the interest/tax circular solve did not converge for every year",
            file=sys.stderr,
        )

    if any(f.unmet_financing_gap > 0 for f in forecasts):
        print(
            "\nwarning: the revolver limit could not cover every year's cash shortfall "
            "(see 'Gap' above) — this is a real financing gap, not a bug; the balance "
            "check above still passes (it checks wiring, not financing feasibility)",
            file=sys.stderr,
        )

    try:
        assert_balance_sheet_balances(forecasts, tolerance=DEFAULT_BALANCE_TOLERANCE)
    except AssertionError as exc:
        print(f"\nBALANCE CHECK FAILED: {exc}", file=sys.stderr)
        return 1

    print("\nbalance check passed for every forecast year: assets = liabilities + equity")

    if contract_path is not None:
        contract = to_fundamentals_contract(statements, forecasts)
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_text(json.dumps(contract, indent=2) + "\n")
        print(f"\nwrote fundamentals contract to {contract_path}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", required=True, help="e.g. GULFOILLUB (no yfinance suffix)")
    parser.add_argument("--financials", default=None, help="defaults to data/<ticker>/financials.csv")
    parser.add_argument("--segments", default=None, help="defaults to data/<ticker>/segment_revenue.csv")
    parser.add_argument("--forecast-years", type=int, default=3, help="years to project forward (>= 1)")
    parser.add_argument("--tax-rate", type=float, default=None, help="override effective tax rate, e.g. 0.26")
    parser.add_argument(
        "--dividend-payout", type=float, default=None, help="override dividend payout ratio, e.g. 0.2 (default 0.0)"
    )
    parser.add_argument(
        "--amort-rate", type=float, default=None, help="override mandatory amortization rate, e.g. 0.10"
    )
    parser.add_argument("--revolver-limit", type=float, default=None, help="override revolver facility size")
    parser.add_argument("--interest-rate", type=float, default=None, help="override interest rate, e.g. 0.065")
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
    parser.add_argument(
        "--contract",
        default=None,
        help="write the v0.8 fundamentals contract block (see model.linkage.to_fundamentals_contract) as "
        "JSON to this path, for the spine to read as a file -- never as a Python import. Requires "
        "--forecast-years >= 3 and a passing balance check.",
    )
    args = parser.parse_args(argv)

    if args.contract and args.forecast_years < 3:
        parser.error("--contract requires --forecast-years >= 3 (the fy3 contract needs a third forecast year)")

    financials_path = Path(args.financials) if args.financials else default_financials_path(args.ticker)
    segment_path = Path(args.segments) if args.segments else default_segment_path(args.ticker)
    return run(
        args.ticker,
        financials_path,
        segment_path,
        args.forecast_years,
        args.tax_rate,
        args.dividend_payout,
        args.amort_rate,
        args.revolver_limit,
        args.interest_rate,
        args.circular,
        args.trailing_years,
        Path(args.contract) if args.contract else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())

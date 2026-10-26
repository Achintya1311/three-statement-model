"""Day 2 CLI: driver-based revenue build — domestic vs. export segments.

    python -m model.revenue --ticker GULFOILLUB
    python -m model.revenue --ticker GULFOILLUB --forecast-years 3
    python -m model.revenue --ticker GULFOILLUB --forecast-years 3 \\
        --domestic-growth 0.10 --export-growth 0.15

Loads ``data/<ticker>/financials.csv`` and ``data/<ticker>/segment_revenue.csv``
via ``model.revenue_driver``, prints the reconciled domestic/export revenue
per historical fiscal year plus each segment's own historical CAGR, then
forecasts forward using each segment's own growth rate (its CAGR by default,
overridable per segment) — never one blended top-line growth percentage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model import DISCLAIMER
from model.revenue_driver import forecast_revenue, load_segment_revenue, segment_cagr

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
    domestic_growth: float | None,
    export_growth: float | None,
) -> int:
    if not financials_path.exists():
        print(f"no financials data at {financials_path}", file=sys.stderr)
        return 1
    if not segment_path.exists():
        print(f"no segment revenue data at {segment_path}", file=sys.stderr)
        return 1

    try:
        segments = load_segment_revenue(financials_path, segment_path)
    except ValueError as exc:
        print(f"segment revenue build failed: {exc}", file=sys.stderr)
        return 1

    print(f"{ticker}: {len(segments)} fiscal years of domestic/export revenue (Rs Lakh)")
    print(f"{'Fiscal year':<12} {'Domestic':>14} {'Export':>12} {'Export share':>13}")
    for s in segments:
        print(
            f"{s.fiscal_year:<12} {s.domestic_revenue:>14,.2f} {s.export_revenue:>12,.2f} "
            f"{s.export_share:>13.2%}"
        )

    d_cagr = segment_cagr(segments, "domestic_revenue")
    e_cagr = segment_cagr(segments, "export_revenue")
    print(
        f"\nhistorical CAGR {segments[0].fiscal_year}->{segments[-1].fiscal_year}: "
        f"domestic {d_cagr:+.2%}, export {e_cagr:+.2%}"
    )

    if forecast_years > 0:
        forecasts = forecast_revenue(segments, forecast_years, domestic_growth, export_growth)
        used_d = domestic_growth if domestic_growth is not None else d_cagr
        used_e = export_growth if export_growth is not None else e_cagr
        print(f"\nforecast ({forecast_years}y, domestic @ {used_d:+.2%}, export @ {used_e:+.2%}):")
        print(f"{'Fiscal year':<12} {'Domestic':>14} {'Export':>12} {'Total':>14}")
        for f in forecasts:
            print(
                f"{f.fiscal_year:<12} {f.domestic_revenue:>14,.2f} {f.export_revenue:>12,.2f} "
                f"{f.total_revenue:>14,.2f}"
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", required=True, help="e.g. GULFOILLUB (no yfinance suffix)")
    parser.add_argument("--financials", default=None, help="defaults to data/<ticker>/financials.csv")
    parser.add_argument("--segments", default=None, help="defaults to data/<ticker>/segment_revenue.csv")
    parser.add_argument("--forecast-years", type=int, default=3, help="years to project forward (0 to skip)")
    parser.add_argument("--domestic-growth", type=float, default=None, help="override domestic CAGR, e.g. 0.10")
    parser.add_argument("--export-growth", type=float, default=None, help="override export CAGR, e.g. 0.15")
    args = parser.parse_args(argv)
    print(DISCLAIMER)

    financials_path = Path(args.financials) if args.financials else default_financials_path(args.ticker)
    segment_path = Path(args.segments) if args.segments else default_segment_path(args.ticker)
    return run(
        args.ticker,
        financials_path,
        segment_path,
        args.forecast_years,
        args.domestic_growth,
        args.export_growth,
    )


if __name__ == "__main__":
    raise SystemExit(main())

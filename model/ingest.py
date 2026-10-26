"""Day 1 CLI: ingest a ticker's historical financials and report the normalized schema.

    python -m model.ingest --ticker GULFOILLUB
    python -m model.ingest --ticker GULFOILLUB --data data/GULFOILLUB/financials.csv

Loads ``data/<ticker>/financials.csv`` via ``model.historical``, runs its
identity checks, and prints one row per fiscal year (revenue, EBIT margin,
net margin, net debt) plus a pass/fail line for the checks themselves. Later
days' modules import ``model.historical.load_historical_statements``
directly rather than re-parsing CSVs of their own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model import DISCLAIMER
from model.historical import load_historical_statements

ROOT = Path(__file__).resolve().parent.parent


def default_data_path(ticker: str) -> Path:
    return ROOT / "data" / ticker / "financials.csv"


def run(ticker: str, data_path: Path) -> int:
    if not data_path.exists():
        print(f"no financials data at {data_path}", file=sys.stderr)
        return 1

    try:
        statements = load_historical_statements(data_path)
    except ValueError as exc:
        print(f"ingestion failed: {exc}", file=sys.stderr)
        return 1

    print(f"{ticker}: {len(statements)} fiscal years ingested from {data_path}, identity checks passed")
    print(f"{'Fiscal year':<12} {'Revenue':>14} {'EBIT margin':>12} {'Net margin':>11} {'Net debt':>14}")
    for s in statements:
        print(
            f"{s.fiscal_year:<12} {s.income.revenue:>14,.2f} {s.income.ebit_margin:>12.2%} "
            f"{s.income.net_margin:>11.2%} {s.balance_sheet.net_debt:>14,.2f}"
        )

    first, last = statements[0], statements[-1]
    years = int(last.fiscal_year[2:6]) - int(first.fiscal_year[2:6])
    if years > 0:
        revenue_cagr = (last.income.revenue / first.income.revenue) ** (1 / years) - 1
        print(f"\nrevenue CAGR {first.fiscal_year}->{last.fiscal_year} ({years}y): {revenue_cagr:+.2%}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", required=True, help="e.g. GULFOILLUB (no yfinance suffix)")
    parser.add_argument("--data", default=None, help="defaults to data/<ticker>/financials.csv")
    args = parser.parse_args(argv)
    print(DISCLAIMER)

    data_path = Path(args.data) if args.data else default_data_path(args.ticker)
    return run(args.ticker, data_path)


if __name__ == "__main__":
    raise SystemExit(main())

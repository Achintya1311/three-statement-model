"""Day 7 CLI: sensitivity tables on the two assumptions that actually move
the answer.

    python -m model.sensitivity --ticker GULFOILLUB
    python -m model.sensitivity --ticker GULFOILLUB --forecast-years 3 --no-circular
    python -m model.sensitivity --ticker GULFOILLUB --steps 1

This project exposes ten override flags across Day 2/3/4/5 (domestic/export
growth, the four Day 3 margins, tax rate, interest rate, dividend payout,
amortization rate). NEXT_STEPS.md asks for the *two* that "actually move the
answer" — rather than assume which two (a reasonable-looking guess like
"growth and margin" is exactly the kind of unchecked intuition this
portfolio's own ground rules distrust), this module measures it: each lever
is shocked up and down from its own real default (the same trailing-average/
historical-CAGR/implied-rate defaults ``model.linkage.forecast_full_linkage``
already resolves when an override is omitted), one at a time, holding every
other lever at default, and ranked by how far it moves FY-final net debt /
EBITDA.

Net debt/EBITDA (FY-final), not ``fy3_revenue_cagr`` or ``fy3_ebit_margin``,
is the ranking target on purpose: a growth override is *the* revenue CAGR by
construction, and an EBITDA-margin override is *the* EBIT margin net of a
roughly stable D&A margin — ranking against either of those would just prove
that overriding a number changes that same number. Net debt/EBITDA is a
genuinely downstream result of all ten levers combined (growth and margin
drive EBITDA's absolute size; capex/NWC/tax/interest/dividends/amortization
drive how much of it becomes debt paydown or cash build), so it is the one
output a ranking against it is actually informative about.

The two highest-ranked levers get the 2-D "data table" grid: a small range
of values either side of each one's default, every combination run through
the full linkage, net debt/EBITDA tabulated per cell — the CLI equivalent of
Excel's two-variable data table, without a spreadsheet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model.debt_schedule import (
    DEFAULT_AMORTIZATION_RATE,
    build_historical_debt_schedule,
    default_interest_rate,
)
from model.historical import load_historical_statements
from model.linkage import (
    DEFAULT_DIVIDEND_PAYOUT,
    ForecastLinkageYear,
    build_historical_linkage,
    default_tax_rate,
    forecast_full_linkage,
)
from model.revenue_driver import load_segment_revenue, segment_cagr
from model.schedules import DEFAULT_TRAILING_YEARS, build_schedule, trailing_average

ROOT = Path(__file__).resolve().parent.parent

LEVER_ORDER = [
    "domestic_growth",
    "export_growth",
    "ebitda_margin",
    "da_margin",
    "capex_margin",
    "nwc_margin",
    "tax_rate",
    "interest_rate",
    "dividend_payout",
    "amortization_rate",
]

LABELS = {
    "domestic_growth": "Domestic revenue growth",
    "export_growth": "Export revenue growth",
    "ebitda_margin": "EBITDA margin",
    "da_margin": "D&A margin",
    "capex_margin": "Capex margin",
    "nwc_margin": "NWC margin",
    "tax_rate": "Tax rate",
    "interest_rate": "Interest rate",
    "dividend_payout": "Dividend payout",
    "amortization_rate": "Amortization rate",
}

SHOCKS = {
    "domestic_growth": 0.05,
    "export_growth": 0.05,
    "ebitda_margin": 0.02,
    "da_margin": 0.01,
    "capex_margin": 0.01,
    "nwc_margin": 0.02,
    "tax_rate": 0.05,
    "interest_rate": 0.02,
    "dividend_payout": 0.20,
    "amortization_rate": 0.05,
}

NO_FLOOR = {"domestic_growth", "export_growth"}
"""Every other lever is a rate/margin that cannot honestly go negative in
this model (a negative capex margin, tax rate or payout ratio is not a real
scenario); growth is the one lever a declining segment can genuinely have."""


def default_financials_path(ticker: str) -> Path:
    return ROOT / "data" / ticker / "financials.csv"


def default_segment_path(ticker: str) -> Path:
    return ROOT / "data" / ticker / "segment_revenue.csv"


def resolve_base_assumptions(
    statements, segments, trailing_years: int = DEFAULT_TRAILING_YEARS
) -> dict[str, float]:
    """Every lever's real default value — the same resolution
    ``forecast_full_linkage`` performs internally for an omitted override,
    exposed here so each lever is shocked from its actual default rather
    than an arbitrary baseline."""
    historical_linkage = build_historical_linkage(statements)
    historical_debt = build_historical_debt_schedule(statements)
    schedule = build_schedule(statements)
    return {
        "domestic_growth": segment_cagr(segments, "domestic_revenue"),
        "export_growth": segment_cagr(segments, "export_revenue"),
        "ebitda_margin": trailing_average([h.ebitda_margin for h in schedule], trailing_years),
        "da_margin": trailing_average([h.da_margin for h in schedule], trailing_years),
        "capex_margin": trailing_average([h.capex_margin for h in schedule], trailing_years),
        "nwc_margin": trailing_average([h.nwc_margin for h in schedule], trailing_years),
        "tax_rate": default_tax_rate(historical_linkage, trailing_years),
        "interest_rate": default_interest_rate(historical_debt, trailing_years),
        "dividend_payout": DEFAULT_DIVIDEND_PAYOUT,
        "amortization_rate": DEFAULT_AMORTIZATION_RATE,
    }


def shocked_value(name: str, base: float, direction: int) -> float:
    """``base`` moved by one ``SHOCKS[name]`` step in ``direction`` (+1/-1),
    floored at zero for every lever in ``NO_FLOOR``'s complement."""
    value = base + direction * SHOCKS[name]
    if name not in NO_FLOOR:
        value = max(0.0, value)
    return value


def net_debt_to_ebitda(year: ForecastLinkageYear) -> float | None:
    """``(ending total debt - cash) / EBITDA`` for one forecast year — the
    contract's ``net_debt_ebitda_fy3`` figure. Negative means a net cash
    position, not leverage. ``None`` if EBITDA is non-positive (the ratio
    is not meaningful there) rather than a division-by-zero crash."""
    if year.ebitda <= 0:
        return None
    return (year.ending_total_debt - year.cash) / year.ebitda


def run_scenario(
    statements,
    segments,
    forecast_years: int,
    overrides: dict[str, float],
    circular: bool,
    trailing_years: int,
) -> list[ForecastLinkageYear]:
    return forecast_full_linkage(
        statements,
        segments,
        forecast_years,
        circular=circular,
        trailing_years=trailing_years,
        **overrides,
    )


def rank_levers(
    statements,
    segments,
    forecast_years: int,
    circular: bool,
    trailing_years: int,
) -> tuple[list[dict], float | None]:
    """One row per lever, sorted by impact (descending): the larger of the
    two absolute swings in FY-final net debt/EBITDA from shocking that lever
    up or down, every other lever held at its default."""
    base_values = resolve_base_assumptions(statements, segments, trailing_years)
    base_metric = net_debt_to_ebitda(
        run_scenario(statements, segments, forecast_years, {}, circular, trailing_years)[-1]
    )

    rows = []
    for name in LEVER_ORDER:
        base = base_values[name]
        down_val = shocked_value(name, base, -1)
        up_val = shocked_value(name, base, +1)
        down_metric = net_debt_to_ebitda(
            run_scenario(statements, segments, forecast_years, {name: down_val}, circular, trailing_years)[-1]
        )
        up_metric = net_debt_to_ebitda(
            run_scenario(statements, segments, forecast_years, {name: up_val}, circular, trailing_years)[-1]
        )
        swings = [
            abs(m - base_metric)
            for m in (down_metric, up_metric)
            if m is not None and base_metric is not None
        ]
        impact = max(swings) if swings else 0.0
        rows.append(
            {
                "name": name,
                "base": base,
                "down_value": down_val,
                "down_metric": down_metric,
                "up_value": up_val,
                "up_metric": up_metric,
                "impact": impact,
            }
        )

    rows.sort(key=lambda r: r["impact"], reverse=True)
    return rows, base_metric


def _dedupe(values: list[float]) -> list[float]:
    """Drop values that collide after flooring (e.g. a lever whose default
    sits at zero collapses every negative step to the same 0.0), preserving
    order, rather than printing the same grid row/column twice."""
    seen: set[float] = set()
    out = []
    for v in values:
        key = round(v, 10)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def sensitivity_grid(
    statements,
    segments,
    forecast_years: int,
    row_var: str,
    col_var: str,
    circular: bool,
    trailing_years: int,
    steps: int = 2,
) -> tuple[list[float], list[float], list[list[float | None]]]:
    """FY-final net debt/EBITDA over every combination of ``row_var`` and
    ``col_var`` at up to ``2 * steps + 1`` values each side of their own
    defaults, every other lever held at default — a two-variable data
    table. A lever floored at zero (see ``NO_FLOOR``) can contribute fewer
    distinct rows/columns than ``steps`` implies, once its negative steps
    collapse onto zero."""
    base_values = resolve_base_assumptions(statements, segments, trailing_years)
    row_values = [
        base_values[row_var] + step * SHOCKS[row_var] for step in range(-steps, steps + 1)
    ]
    col_values = [
        base_values[col_var] + step * SHOCKS[col_var] for step in range(-steps, steps + 1)
    ]
    if row_var not in NO_FLOOR:
        row_values = [max(0.0, v) for v in row_values]
    if col_var not in NO_FLOOR:
        col_values = [max(0.0, v) for v in col_values]
    row_values = _dedupe(row_values)
    col_values = _dedupe(col_values)

    table = []
    for rv in row_values:
        row = []
        for cv in col_values:
            forecasts = run_scenario(
                statements, segments, forecast_years, {row_var: rv, col_var: cv}, circular, trailing_years
            )
            row.append(net_debt_to_ebitda(forecasts[-1]))
        table.append(row)
    return row_values, col_values, table


def _fmt_pct(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "n/a"


def _fmt_metric(value: float | None) -> str:
    return f"{value:.2f}x" if value is not None else "n/a"


def run(
    ticker: str,
    financials_path: Path,
    segment_path: Path,
    forecast_years: int,
    circular: bool,
    trailing_years: int,
    steps: int,
) -> int:
    if not financials_path.exists():
        print(f"no financials data at {financials_path}", file=sys.stderr)
        return 1
    if not segment_path.exists():
        print(f"no segment revenue data at {segment_path}", file=sys.stderr)
        return 1
    if forecast_years < 1:
        print("--forecast-years must be >= 1", file=sys.stderr)
        return 1

    try:
        statements = load_historical_statements(financials_path)
        segments = load_segment_revenue(financials_path, segment_path)
    except ValueError as exc:
        print(f"sensitivity build failed: {exc}", file=sys.stderr)
        return 1

    mode = "circular" if circular else "non-circular"
    rows, base_metric = rank_levers(statements, segments, forecast_years, circular, trailing_years)
    final_fy = run_scenario(statements, segments, forecast_years, {}, circular, trailing_years)[-1].fiscal_year

    print(
        f"{ticker}: Day 7 sensitivity ranking — impact on {final_fy} net debt/EBITDA "
        f"({forecast_years}y forecast, {mode} interest)"
    )
    print(f"base case: {_fmt_metric(base_metric)}\n")
    print(f"{'Rank':<5}{'Assumption':<26}{'Base':>10}{'Down':>12}{'-> metric':>12}{'Up':>12}{'-> metric':>12}{'Impact':>10}")
    for i, row in enumerate(rows, start=1):
        print(
            f"{i:<5}{LABELS[row['name']]:<26}{_fmt_pct(row['base']):>10}"
            f"{_fmt_pct(row['down_value']):>12}{_fmt_metric(row['down_metric']):>12}"
            f"{_fmt_pct(row['up_value']):>12}{_fmt_metric(row['up_metric']):>12}"
            f"{row['impact']:>10.2f}"
        )

    top_two = [rows[0]["name"], rows[1]["name"]]
    print(f"\nthe two assumptions that actually move the answer: {LABELS[top_two[0]]}, {LABELS[top_two[1]]}")

    row_var, col_var = top_two
    row_values, col_values, table = sensitivity_grid(
        statements, segments, forecast_years, row_var, col_var, circular, trailing_years, steps
    )
    print(
        f"\n{final_fy} net debt/EBITDA — {LABELS[row_var]} (rows) x {LABELS[col_var]} (columns)"
    )
    header = " " * 26 + "".join(f"{_fmt_pct(cv):>12}" for cv in col_values)
    print(header)
    for rv, row in zip(row_values, table):
        print(f"{_fmt_pct(rv):<26}" + "".join(f"{_fmt_metric(v):>12}" for v in row))

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", required=True, help="e.g. GULFOILLUB (no yfinance suffix)")
    parser.add_argument("--financials", default=None, help="defaults to data/<ticker>/financials.csv")
    parser.add_argument("--segments", default=None, help="defaults to data/<ticker>/segment_revenue.csv")
    parser.add_argument("--forecast-years", type=int, default=3, help="years to project forward (>= 1)")
    parser.add_argument(
        "--steps", type=int, default=2, help="shock steps either side of default in the 2-D grid (>= 1)"
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

    if args.steps < 1:
        print("--steps must be >= 1", file=sys.stderr)
        return 1

    financials_path = Path(args.financials) if args.financials else default_financials_path(args.ticker)
    segment_path = Path(args.segments) if args.segments else default_segment_path(args.ticker)
    return run(
        args.ticker,
        financials_path,
        segment_path,
        args.forecast_years,
        args.circular,
        args.trailing_years,
        args.steps,
    )


if __name__ == "__main__":
    raise SystemExit(main())

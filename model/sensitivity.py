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

from model import DISCLAIMER
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


def scenario_flags(forecasts: list[ForecastLinkageYear]) -> str:
    """The same two checks ``model.statements``'/``model.debt``'s own CLIs
    already apply to the base case (P60), applied to one shocked scenario's
    full forecast: a non-empty result means the metric computed from this
    scenario comes from a year that either couldn't fund itself through the
    revolver (``unmet_financing_gap > 0``) or whose interest/tax circular
    solve didn't converge -- not a bug, but not a fully resolved number
    either. Empty string when every year is clean."""
    flags = []
    if any(f.unmet_financing_gap > 0 for f in forecasts):
        flags.append("gap")
    if any(not (f.debt_converged and f.tax_converged) for f in forecasts):
        flags.append("non-conv")
    return "+".join(flags)


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
        down_forecasts = run_scenario(statements, segments, forecast_years, {name: down_val}, circular, trailing_years)
        up_forecasts = run_scenario(statements, segments, forecast_years, {name: up_val}, circular, trailing_years)
        down_metric = net_debt_to_ebitda(down_forecasts[-1])
        up_metric = net_debt_to_ebitda(up_forecasts[-1])
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
                "down_flag": scenario_flags(down_forecasts),
                "up_value": up_val,
                "up_metric": up_metric,
                "up_flag": scenario_flags(up_forecasts),
                "impact": impact,
            }
        )

    rows.sort(key=lambda r: r["impact"], reverse=True)
    return rows, base_metric


TRAILING_WINDOW_CHECK_YEARS = (5,)
"""Extra trailing-average windows checked against the real
``DEFAULT_TRAILING_YEARS``=3 baseline by :func:`trailing_window_robustness_check`
(P61), alongside a full-history window derived from the data itself (see
that function)."""


def trailing_window_robustness_check(
    statements,
    segments,
    forecast_years: int,
    circular: bool,
) -> dict:
    """Rerun the Day 7 ranking and FY-final net debt/EBITDA base case at a
    5-year and a full-history trailing-average window, instead of the real
    ``DEFAULT_TRAILING_YEARS``=3 default, and report honestly whether either
    the top-two lever order or the metric's sign changes (P61).

    Mirrors ``reverse_dcf.grill.roic_anchor_robustness_check`` (V14, this
    same fix phase's Day 65) in a sibling repo: a baseline at the real
    default, one result per alternate window, and a changed/unchanged
    verdict read off the real numbers rather than assumed. The full-history
    window is derived from ``len(statements)`` rather than hardcoded, so it
    always covers every historical fiscal year the fixture actually has.
    Only the six trailing-average levers (``ebitda_margin``, ``da_margin``,
    ``capex_margin``, ``nwc_margin``, ``tax_rate``, ``interest_rate``) can
    move between windows at all -- ``dividend_payout``/``amortization_rate``
    are fixed constants and ``domestic_growth``/``export_growth`` are
    already whole-history CAGRs -- so a change here would come from one of
    those six shifting enough to overtake the baseline's own top two.
    """
    full_history_years = len(statements)
    windows = sorted({*TRAILING_WINDOW_CHECK_YEARS, full_history_years})

    baseline_rows, baseline_metric = rank_levers(
        statements, segments, forecast_years, circular, DEFAULT_TRAILING_YEARS
    )
    baseline_top_two = (baseline_rows[0]["name"], baseline_rows[1]["name"])

    by_window: dict[int, dict] = {}
    for window in windows:
        rows, metric = rank_levers(statements, segments, forecast_years, circular, window)
        top_two = (rows[0]["name"], rows[1]["name"])
        sign_changed = (
            metric is not None
            and baseline_metric is not None
            and (metric > 0) != (baseline_metric > 0)
        )
        by_window[window] = {
            "top_two": top_two,
            "base_metric": metric,
            "ranking_changed": top_two != baseline_top_two,
            "metric_sign_changed": sign_changed,
        }

    return {
        "baseline_trailing_years": DEFAULT_TRAILING_YEARS,
        "baseline_top_two": baseline_top_two,
        "baseline_metric": baseline_metric,
        "full_history_years": full_history_years,
        "by_window": by_window,
        "ranking_changes_any_window": any(r["ranking_changed"] for r in by_window.values()),
        "metric_sign_changes_any_window": any(
            r["metric_sign_changed"] for r in by_window.values()
        ),
    }


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
) -> tuple[list[float], list[float], list[list[float | None]], list[list[str]]]:
    """FY-final net debt/EBITDA over every combination of ``row_var`` and
    ``col_var`` at up to ``2 * steps + 1`` values each side of their own
    defaults, every other lever held at default — a two-variable data
    table. A lever floored at zero (see ``NO_FLOOR``) can contribute fewer
    distinct rows/columns than ``steps`` implies, once its negative steps
    collapse onto zero. The fourth return value is a same-shape grid of
    ``scenario_flags`` strings (P60), one per cell, so a caller can tell a
    cell that isn't fully resolved (a financing gap or a convergence
    failure somewhere in that cell's own forecast) from one that is."""
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
    flags = []
    for rv in row_values:
        row = []
        flag_row = []
        for cv in col_values:
            forecasts = run_scenario(
                statements, segments, forecast_years, {row_var: rv, col_var: cv}, circular, trailing_years
            )
            row.append(net_debt_to_ebitda(forecasts[-1]))
            flag_row.append(scenario_flags(forecasts))
        table.append(row)
        flags.append(flag_row)
    return row_values, col_values, table, flags


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
    base_forecasts = run_scenario(statements, segments, forecast_years, {}, circular, trailing_years)
    final_fy = base_forecasts[-1].fiscal_year

    if any(f.unmet_financing_gap > 0 for f in base_forecasts):
        print(
            "\nwarning: the base case itself has a year the revolver limit couldn't cover "
            "(see model.statements/model.debt for the per-year gap) — this is a real "
            "financing gap, not a bug",
            file=sys.stderr,
        )

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

    flagged_rows = [row for row in rows if row["down_flag"] or row["up_flag"]]
    if flagged_rows:
        print(
            "\nwarning: the shocked metric below isn't fully resolved for every lever "
            "(a financing gap the revolver couldn't cover, and/or a circular solve that "
            "didn't converge) — see model.statements/model.debt; not a bug:",
            file=sys.stderr,
        )
        for row in flagged_rows:
            for direction, flag in (("down", row["down_flag"]), ("up", row["up_flag"])):
                if flag:
                    print(f"  {LABELS[row['name']]} ({direction}): {flag}", file=sys.stderr)

    top_two = [rows[0]["name"], rows[1]["name"]]
    print(f"\nthe two assumptions that actually move the answer: {LABELS[top_two[0]]}, {LABELS[top_two[1]]}")

    row_var, col_var = top_two
    row_values, col_values, table, grid_flags = sensitivity_grid(
        statements, segments, forecast_years, row_var, col_var, circular, trailing_years, steps
    )
    print(
        f"\n{final_fy} net debt/EBITDA — {LABELS[row_var]} (rows) x {LABELS[col_var]} (columns)"
    )
    header = " " * 26 + "".join(f"{_fmt_pct(cv):>12}" for cv in col_values)
    print(header)
    for rv, row in zip(row_values, table):
        print(f"{_fmt_pct(rv):<26}" + "".join(f"{_fmt_metric(v):>12}" for v in row))

    flagged_cells = [
        (rv, cv, flag)
        for rv, flag_row in zip(row_values, grid_flags)
        for cv, flag in zip(col_values, flag_row)
        if flag
    ]
    if flagged_cells:
        print(
            "\nwarning: the grid above has cells that aren't fully resolved "
            "(a financing gap and/or a non-converged circular solve); not a bug:",
            file=sys.stderr,
        )
        for rv, cv, flag in flagged_cells:
            print(
                f"  {LABELS[row_var]}={_fmt_pct(rv)}, {LABELS[col_var]}={_fmt_pct(cv)}: {flag}",
                file=sys.stderr,
            )

    robustness = trailing_window_robustness_check(statements, segments, forecast_years, circular)
    print(
        f"\ntrailing-window robustness check — ranking and {final_fy} net debt/EBITDA "
        f"at a 5yr and a full-history ({robustness['full_history_years']}yr) trailing-average "
        f"window, vs. the real {robustness['baseline_trailing_years']}yr default:"
    )
    print(f"  {robustness['baseline_trailing_years']}yr (baseline): "
          f"top two {LABELS[robustness['baseline_top_two'][0]]}, "
          f"{LABELS[robustness['baseline_top_two'][1]]}; "
          f"base case {_fmt_metric(robustness['baseline_metric'])}")
    for window, result in robustness["by_window"].items():
        tag = "5yr" if window == 5 else f"full-history ({window}yr)"
        verdict = []
        if result["ranking_changed"]:
            verdict.append("ranking CHANGED")
        if result["metric_sign_changed"]:
            verdict.append("metric sign CHANGED")
        verdict_str = ", ".join(verdict) if verdict else "conclusion holds"
        print(
            f"  {tag}: top two {LABELS[result['top_two'][0]]}, {LABELS[result['top_two'][1]]}; "
            f"base case {_fmt_metric(result['base_metric'])} — {verdict_str}"
        )
    if robustness["ranking_changes_any_window"] or robustness["metric_sign_changes_any_window"]:
        print(
            "\nwarning: the Day 7 headline conclusion is not robust to the trailing-average "
            "window choice — see the robustness check above",
            file=sys.stderr,
        )

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
    print(DISCLAIMER)

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

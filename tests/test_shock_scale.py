"""P149: the Day 7 ranking at shocks scaled to each lever's own historical
dispersion, beside the fixed hand-picked steps."""

import statistics
from pathlib import Path

import pytest

from model import sensitivity
from model.debt_schedule import build_historical_debt_schedule
from model.historical import load_historical_statements
from model.linkage import build_historical_linkage
from model.revenue_driver import load_segment_revenue
from model.schedules import build_schedule

ROOT = Path(__file__).resolve().parent.parent
GULFOILLUB_CSV = ROOT / "data" / "GULFOILLUB" / "financials.csv"
SEGMENT_CSV = ROOT / "data" / "GULFOILLUB" / "segment_revenue.csv"


def _real_inputs():
    statements = load_historical_statements(GULFOILLUB_CSV)
    return statements, load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)


def test_historical_shocks_are_each_levers_sample_sd():
    statements, segments = _real_inputs()
    shocks = sensitivity.historical_shocks(statements, segments)
    schedule = build_schedule(statements)
    for name in ("ebitda_margin", "da_margin", "capex_margin", "nwc_margin"):
        assert shocks[name] == pytest.approx(statistics.stdev(getattr(h, name) for h in schedule))
    domestic = [s.domestic_revenue for s in segments]
    assert shocks["domestic_growth"] == pytest.approx(
        statistics.stdev(b / a - 1 for a, b in zip(domestic, domestic[1:]))
    )
    taxes = [h.effective_tax_rate for h in build_historical_linkage(statements) if h.effective_tax_rate is not None]
    assert shocks["tax_rate"] == pytest.approx(statistics.stdev(taxes))
    rates = [
        h.implied_interest_rate
        for h in build_historical_debt_schedule(statements)
        if h.implied_interest_rate is not None
    ]
    assert shocks["interest_rate"] == pytest.approx(statistics.stdev(rates))
    # no data behind these two: they keep the fixed step
    for name in ("dividend_payout", "amortization_rate"):
        assert shocks[name] == sensitivity.SHOCKS[name]


def test_rank_levers_uses_the_shocks_it_is_given():
    statements, segments = _real_inputs()
    shocks = sensitivity.historical_shocks(statements, segments)
    rows, _ = sensitivity.rank_levers(statements, segments, 3, True, 3, shocks=shocks)
    by_name = {r["name"]: r for r in rows}
    capex = by_name["capex_margin"]
    assert capex["up_value"] == pytest.approx(capex["base"] + shocks["capex_margin"])
    fixed_rows, _ = sensitivity.rank_levers(statements, segments, 3, True, 3)
    assert {r["name"]: r["impact"] for r in fixed_rows} != {r["name"]: r["impact"] for r in rows}


def test_cli_prints_the_historical_steps(capsys):
    assert sensitivity.main(["--ticker", "GULFOILLUB", "--shock-scale", "historical"]) == 0
    out = capsys.readouterr().out
    assert "shock scale: historical" in out
    assert "fixed step (no data)" in out

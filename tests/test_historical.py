"""Day 1 tests: normalized-schema ingestion, identity checks, and the CLI
end to end against the real committed GULFOILLUB fixture."""

import io
from pathlib import Path

import pandas as pd
import pytest

from model import historical, ingest

ROOT = Path(__file__).resolve().parent.parent
GULFOILLUB_CSV = ROOT / "data" / "GULFOILLUB" / "financials.csv"

GOOD_ROW = {
    "fiscal_year": "FY2023-24",
    "revenue": "328409.68",
    "ebitda": "48583.9",
    "depreciation_amortization": "4677.45",
    "ebit": "43906.45",
    "interest_expense": "2560.94",
    "tax_expense": "10535.66",
    "net_profit": "30809.85",
    "total_assets": "230449.91",
    "total_debt": "32931.01",
    "cash_and_equivalents": "70223.75",
    "net_working_capital": "47469.15",
    "capex": "2191.05",
    "shares_outstanding": "49168433",
}


def write_csv(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "financials.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_load_financials_csv_reads_the_real_committed_fixture():
    df = historical.load_financials_csv(GULFOILLUB_CSV)
    assert list(df.columns) == historical.REQUIRED_COLUMNS
    assert len(df) == 10
    assert df["fiscal_year"].iloc[0] == "FY2014-15"
    assert df["fiscal_year"].iloc[-1] == "FY2023-24"


def test_load_financials_csv_rejects_missing_columns(tmp_path):
    bad = write_csv(tmp_path, [{k: v for k, v in GOOD_ROW.items() if k != "ebit"}])
    with pytest.raises(ValueError, match="missing columns"):
        historical.load_financials_csv(bad)


def test_load_financials_csv_rejects_duplicate_fiscal_years(tmp_path):
    bad = write_csv(tmp_path, [GOOD_ROW, GOOD_ROW])
    with pytest.raises(ValueError, match="duplicate fiscal_year"):
        historical.load_financials_csv(bad)


def test_to_numeric_rejects_non_numeric_cells(tmp_path):
    bad_row = {**GOOD_ROW, "revenue": "not-a-number"}
    bad = write_csv(tmp_path, [bad_row])
    df = historical.load_financials_csv(bad)
    with pytest.raises(ValueError, match="non-numeric"):
        historical.to_numeric(df)


def test_check_identities_passes_on_the_real_fixture():
    df = historical.load_financials_csv(GULFOILLUB_CSV)
    failures = historical.check_identities(df)
    assert failures == {"ebit_identity": [], "net_profit_identity": []}


def test_check_identities_catches_an_ebit_mismatch(tmp_path):
    bad_row = {**GOOD_ROW, "ebit": "999999"}
    bad = write_csv(tmp_path, [bad_row])
    df = historical.load_financials_csv(bad)
    failures = historical.check_identities(df)
    assert failures["ebit_identity"] == ["FY2023-24"]


def test_check_identities_catches_a_net_profit_mismatch(tmp_path):
    bad_row = {**GOOD_ROW, "net_profit": "1"}
    bad = write_csv(tmp_path, [bad_row])
    df = historical.load_financials_csv(bad)
    failures = historical.check_identities(df)
    assert failures["net_profit_identity"] == ["FY2023-24"]


def test_load_historical_statements_raises_on_an_identity_failure(tmp_path):
    bad_row = {**GOOD_ROW, "ebit": "999999"}
    bad = write_csv(tmp_path, [bad_row])
    with pytest.raises(ValueError, match="identity check failed"):
        historical.load_historical_statements(bad)


def test_load_historical_statements_normalizes_the_real_fixture_sorted_by_year():
    statements = historical.load_historical_statements(GULFOILLUB_CSV)
    assert len(statements) == 10
    assert [s.fiscal_year for s in statements] == sorted(s.fiscal_year for s in statements)
    assert statements[0].fiscal_year == "FY2014-15"
    assert statements[-1].fiscal_year == "FY2023-24"


def test_historical_statement_fields_round_trip_the_last_fiscal_year():
    statements = historical.load_historical_statements(GULFOILLUB_CSV)
    last = statements[-1]
    assert last.fiscal_year == "FY2023-24"
    assert last.income.revenue == pytest.approx(328409.68)
    assert last.income.net_profit == pytest.approx(30809.85)
    assert last.balance_sheet.total_assets == pytest.approx(230449.91)
    assert last.cash_flow.capex == pytest.approx(2191.05)
    assert last.shares_outstanding == pytest.approx(49168433)


def test_income_statement_derived_properties():
    statements = historical.load_historical_statements(GULFOILLUB_CSV)
    last = statements[-1]
    assert last.income.pretax_income == pytest.approx(43906.45 - 2560.94)
    assert last.income.ebit_margin == pytest.approx(43906.45 / 328409.68)
    assert last.income.net_margin == pytest.approx(30809.85 / 328409.68)


def test_balance_sheet_net_debt():
    statements = historical.load_historical_statements(GULFOILLUB_CSV)
    last = statements[-1]
    assert last.balance_sheet.net_debt == pytest.approx(32931.01 - 70223.75)


def test_balance_sheet_summary_has_no_equity_field():
    """The source data has no liabilities/equity breakdown (see research/sources.md);
    this schema must not invent one."""
    assert not hasattr(historical.BalanceSheetSummary, "total_equity")


def test_ingest_default_data_path():
    assert ingest.default_data_path("GULFOILLUB") == ROOT / "data" / "GULFOILLUB" / "financials.csv"


def test_ingest_run_against_the_real_fixture(capsys):
    exit_code = ingest.run("GULFOILLUB", GULFOILLUB_CSV)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "10 fiscal years ingested" in out
    assert "FY2023-24" in out
    assert "revenue CAGR" in out


def test_ingest_run_reports_a_missing_file_cleanly(tmp_path, capsys):
    exit_code = ingest.run("NOPE", tmp_path / "missing.csv")
    assert exit_code == 1
    assert "no financials data at" in capsys.readouterr().err


def test_ingest_run_reports_an_identity_failure_cleanly(tmp_path, capsys):
    bad_row = {**GOOD_ROW, "ebit": "999999"}
    bad = write_csv(tmp_path, [bad_row])
    exit_code = ingest.run("BAD", bad)
    assert exit_code == 1
    assert "ingestion failed" in capsys.readouterr().err


def test_main_cli_end_to_end_against_the_real_fixture(capsys):
    exit_code = ingest.main(["--ticker", "GULFOILLUB"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "GULFOILLUB: 10 fiscal years ingested" in out


def test_main_cli_accepts_an_explicit_data_path(capsys):
    exit_code = ingest.main(["--ticker", "GULFOILLUB", "--data", str(GULFOILLUB_CSV)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "GULFOILLUB: 10 fiscal years ingested" in out

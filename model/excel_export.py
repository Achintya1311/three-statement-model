"""Day 6: Excel export carrying live formulas, not pasted values.

Every number a reader could ask "where did this come from?" about is either
a cell in the **Assumptions** sheet (editable, yellow-filled, the only place
a rate/margin/limit is typed in) or a formula on the **Forecast** sheet that
chains off the previous column and off Assumptions cells — never a Python
float baked into a formula string. The one exception, by construction and
flagged here as such: the **Base** column (the last historical fiscal year)
holds the real historical stock figures themselves — cash, debt, "other
assets", "equity and other liabilities" — because those are facts read off
the filings, not a forecast formula's output. Nothing past that column is a
literal.

**Scope decision, and why.** ``model.linkage.forecast_full_linkage`` resolves
two circularities: Day 4's own interest-vs-average-debt-balance circularity
(the ``--circular``/``--no-circular`` toggle), and a second, outer one this
module's own Day 5 docstring describes (cash tax depends on interest, which
depends on the debt schedule, which depends on CFADS, which is now net of
cash tax). This exporter builds the workbook in **non-circular** mode only
(interest on the *opening* term-debt balance, matching ``model.statements
--no-circular``). That is not a cosmetic simplification — it is what
actually removes *both* circularities at once: when interest depends only on
the opening balance (not on CFADS, which is downstream of tax, which is
downstream of interest), the outer tax/interest loop in ``forecast_
full_linkage`` converges in its very first pass (verified by hand: with
``circular=False``, ``debt_result.interest_expense`` does not depend on the
``interest_guess`` fed into that loop at all, since it is a pure function of
the opening balance). That makes the whole linkage a left-to-right chain of
formulas with no circular references for Excel to iterate — exactly what a
workbook "with live formulas" can represent without turning on Excel's
iterative-calculation setting (a feature this module does not attempt to
configure or rely on). The circular (average-balance) interest mode is
**not** represented in this workbook; a reader who wants that mode still has
``python -m model.statements`` on the circular default. This is a real,
named gap, not a hidden one — see this project's README Limitations.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from model.debt_schedule import (
    DEFAULT_AMORTIZATION_RATE,
    build_historical_debt_schedule,
    default_interest_rate,
    default_revolver_limit,
)
from model.historical import LAKH_TO_RUPEES, HistoricalStatement
from model.linkage import (
    DEFAULT_BALANCE_TOLERANCE,
    DEFAULT_DIVIDEND_PAYOUT,
    build_historical_linkage,
    default_tax_rate,
)
from model.revenue_driver import SegmentRevenue, next_fiscal_year, segment_cagr
from model.schedules import DEFAULT_TRAILING_YEARS, build_schedule, trailing_average

ASSUMPTION_FILL = PatternFill(start_color="FFF9E79F", end_color="FFF9E79F", fill_type="solid")
HEADER_FILL = PatternFill(start_color="FF2C3E50", end_color="FF2C3E50", fill_type="solid")
BASE_FILL = PatternFill(start_color="FFEAEDED", end_color="FFEAEDED", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFFFF")
BOLD = Font(bold=True)
THIN_BOTTOM = Border(bottom=Side(style="thin", color="FFBFBFBF"))

# (row label, note) for the Assumptions sheet, in display order. The key is
# also used to build the named cell reference every Forecast formula reads.
ASSUMPTIONS = [
    ("domestic_growth", "Domestic revenue growth", "Historical CAGR unless overridden at export time"),
    ("export_growth", "Export revenue growth", "Historical CAGR unless overridden at export time"),
    ("ebitda_margin", "EBITDA margin (% of revenue)", "Trailing average unless overridden"),
    ("da_margin", "D&A margin (% of revenue)", "Trailing average unless overridden"),
    ("capex_margin", "Capex margin (% of revenue)", "Trailing average unless overridden"),
    ("nwc_margin", "Net working capital margin (% of revenue)", "Trailing average unless overridden"),
    ("amortization_rate", "Term debt amortization rate (% of opening balance)", "Assumption, not disclosed"),
    ("revolver_limit", "Revolver facility limit", "Assumption: historical peak total debt, unless overridden"),
    ("interest_rate", "Interest rate (on opening term debt)", "Trailing implied rate unless overridden"),
    ("tax_rate", "Effective tax rate", "Trailing average unless overridden"),
    ("dividend_payout", "Dividend payout ratio", "No dividend data exists; 0.0 unless overridden"),
    ("balance_tolerance", "Balance-check tolerance", "Absolute, same units as the source data"),
]

# (row key, label) for the Forecast sheet, in display order. Rows with no
# Base-column entry in BASE_ROW_FORMULAS/BASE_ROW_LITERALS are left blank in
# the Base column — see module docstring on why Base only holds stocks.
FORECAST_ROWS = [
    ("fiscal_year", "Fiscal year"),
    ("domestic_revenue", "Domestic revenue"),
    ("export_revenue", "Export revenue"),
    ("total_revenue", "Total revenue"),
    ("ebitda_margin_used", "EBITDA margin used"),
    ("ebitda", "EBITDA"),
    ("da_margin_used", "D&A margin used"),
    ("da", "Depreciation & amortization"),
    ("ebit", "EBIT"),
    ("amortization_rate_used", "Amortization rate used"),
    ("scheduled_amortization", "Scheduled amortization"),
    ("term_debt", "Term debt (ending balance)"),
    ("interest_rate_used", "Interest rate used (on opening term debt)"),
    ("interest_expense", "Interest expense"),
    ("pretax_income", "Pretax income"),
    ("tax_rate_used", "Tax rate used"),
    ("tax_expense", "Tax expense"),
    ("net_income", "Net income"),
    ("shares_outstanding", "Shares outstanding (held flat, no corporate action modeled)"),
    ("eps", "EPS (Rs/share)"),
    ("dividend_payout_used", "Dividend payout ratio used"),
    ("dividends", "Dividends"),
    ("dividend_per_share", "Dividend per share (Rs/share)"),
    ("capex_margin_used", "Capex margin used"),
    ("capex", "Capex"),
    ("nwc_margin_used", "NWC margin used"),
    ("net_working_capital", "Net working capital"),
    ("delta_nwc", "Delta NWC"),
    ("cfads_after_tax", "CFADS, after tax"),
    ("cash_before_revolver", "Cash before revolver sweep"),
    ("revolver_limit_used", "Revolver limit used"),
    ("revolver_draw", "Revolver draw"),
    ("revolver_repayment", "Revolver repayment"),
    ("revolver_balance", "Revolver balance (ending)"),
    ("unmet_financing_gap", "Unmet financing gap"),
    ("total_debt", "Total debt (ending balance)"),
    ("cfo", "Cash flow from operations"),
    ("cfi", "Cash flow from investing"),
    ("cff", "Cash flow from financing"),
    ("net_change_in_cash", "Net change in cash"),
    ("cash", "Cash (ending balance)"),
    ("other_assets", "Other assets (ending balance)"),
    ("equity_and_other_liabilities", "Equity & other liabilities (ending balance)"),
    ("book_value_per_share", "Book value per share (Rs/share)"),
    ("total_assets", "Total assets"),
    ("total_liabilities_and_equity", "Total liabilities & equity"),
    ("balance_difference", "Balance difference (assets - liab.+equity)"),
    ("balance_check", "Balance check"),
]

# Rows that get a real historical figure in the Base column, as a plain
# value (these are facts read off the filings, not a forecast formula's
# output — see module docstring).
BASE_LITERAL_ROWS = {
    "domestic_revenue",
    "export_revenue",
    "term_debt",
    "net_working_capital",
    "revolver_balance",
    "cash",
    "other_assets",
    "equity_and_other_liabilities",
    "shares_outstanding",
}
# Rows that get a formula in the Base column too, built only from other Base
# cells, so the balance check can be shown to hold trivially in the base
# year as well.
BASE_FORMULA_ROWS = {"total_revenue", "total_debt", "total_assets", "total_liabilities_and_equity"}


def _assumption_ref(sheet_name: str, cell_refs: dict[str, str], key: str) -> str:
    return f"{sheet_name}!${cell_refs[key][0]}${cell_refs[key][1:]}"


def _write_assumptions_sheet(
    wb: Workbook,
    ticker: str,
    values: dict[str, float],
) -> dict[str, str]:
    ws: Worksheet = wb.create_sheet("Assumptions")
    ws["A1"] = f"ASSUMPTIONS — {ticker}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = (
        "Every Forecast formula reads one of the yellow cells below. Change a "
        "number here, not inside a formula, to re-run the model under a "
        "different assumption."
    )
    ws["A2"].font = Font(italic=True, color="FF555555")
    ws.merge_cells("A2:D2")
    ws["A3"] = (
        "Educational research on historical data. Not investment advice. "
        "Not a SEBI-registered research analyst."
    )
    ws["A3"].font = Font(italic=True, color="FF555555")
    ws.merge_cells("A3:D3")

    header_row = 4
    ws.cell(row=header_row, column=1, value="Assumption").font = BOLD
    ws.cell(row=header_row, column=3, value="Value").font = BOLD
    ws.cell(row=header_row, column=4, value="Source / note").font = BOLD

    cell_refs: dict[str, str] = {}
    row = header_row + 1
    for key, label, note in ASSUMPTIONS:
        ws.cell(row=row, column=1, value=label)
        value_cell = ws.cell(row=row, column=3, value=values[key])
        value_cell.fill = ASSUMPTION_FILL
        value_cell.number_format = "0.00%" if key not in ("revolver_limit", "balance_tolerance") else "#,##0.00"
        ws.cell(row=row, column=4, value=note).font = Font(italic=True, color="FF555555")
        cell_refs[key] = f"C{row}"
        row += 1

    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 2
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 52
    return cell_refs


def _write_historical_sheet(ws: Worksheet, ticker: str, statements: list[HistoricalStatement]) -> None:
    ws["A1"] = f"HISTORICAL — {ticker} (as ingested, read-only reference)"
    ws["A1"].font = Font(bold=True, size=14)

    columns = [
        ("fiscal_year", "Fiscal year"),
        ("revenue", "Revenue"),
        ("ebitda", "EBITDA"),
        ("depreciation_amortization", "D&A"),
        ("ebit", "EBIT"),
        ("interest_expense", "Interest expense"),
        ("tax_expense", "Tax expense"),
        ("net_profit", "Net profit"),
        ("total_assets", "Total assets"),
        ("total_debt", "Total debt"),
        ("cash_and_equivalents", "Cash"),
        ("net_working_capital", "Net working capital"),
        ("capex", "Capex"),
    ]
    header_row = 3
    for col_idx, (_, label) in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    for row_offset, s in enumerate(sorted(statements, key=lambda s: s.fiscal_year)):
        row = header_row + 1 + row_offset
        income, bs = s.income, s.balance_sheet
        values = {
            "fiscal_year": s.fiscal_year,
            "revenue": income.revenue,
            "ebitda": income.ebitda,
            "depreciation_amortization": income.depreciation_amortization,
            "ebit": income.ebit,
            "interest_expense": income.interest_expense,
            "tax_expense": income.tax_expense,
            "net_profit": income.net_profit,
            "total_assets": bs.total_assets,
            "total_debt": bs.total_debt,
            "cash_and_equivalents": bs.cash_and_equivalents,
            "net_working_capital": bs.net_working_capital,
            "capex": s.cash_flow.capex,
        }
        for col_idx, (key, _) in enumerate(columns, start=1):
            ws.cell(row=row, column=col_idx, value=values[key])

    for col_idx in range(1, len(columns) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 16


def _col_ref(sheet_name: str, col_letter: str, row: int) -> str:
    return f"{sheet_name}!{col_letter}{row}" if sheet_name else f"{col_letter}{row}"


def build_workbook(
    ticker: str,
    statements: list[HistoricalStatement],
    segments: list[SegmentRevenue],
    forecast_years: int,
    tax_rate: float | None = None,
    dividend_payout: float | None = None,
    amortization_rate: float | None = None,
    revolver_limit: float | None = None,
    interest_rate: float | None = None,
    domestic_growth: float | None = None,
    export_growth: float | None = None,
    ebitda_margin: float | None = None,
    da_margin: float | None = None,
    capex_margin: float | None = None,
    nwc_margin: float | None = None,
    trailing_years: int = DEFAULT_TRAILING_YEARS,
    balance_tolerance: float = DEFAULT_BALANCE_TOLERANCE,
) -> Workbook:
    """Build the full workbook: Assumptions, Historical, Forecast sheets.

    Resolves every assumption not explicitly overridden the same way the
    Day 2/3/4/5 CLIs already do (trailing average or historical CAGR), so
    the Assumptions sheet's defaults match ``python -m model.statements
    --no-circular``'s own defaults exactly. See module docstring for why
    the Forecast sheet's formulas are built in non-circular mode.
    """
    if forecast_years < 1:
        raise ValueError("forecast_years must be >= 1")
    if not statements or not segments:
        raise ValueError("need at least one historical statement and one segment-revenue year")

    historical_linkage = build_historical_linkage(statements)
    historical_debt = build_historical_debt_schedule(statements)
    historical_schedule = build_schedule(statements)

    resolved = {
        "domestic_growth": domestic_growth if domestic_growth is not None else segment_cagr(segments, "domestic_revenue"),
        "export_growth": export_growth if export_growth is not None else segment_cagr(segments, "export_revenue"),
        "ebitda_margin": ebitda_margin
        if ebitda_margin is not None
        else trailing_average([h.ebitda_margin for h in historical_schedule], trailing_years),
        "da_margin": da_margin
        if da_margin is not None
        else trailing_average([h.da_margin for h in historical_schedule], trailing_years),
        "capex_margin": capex_margin
        if capex_margin is not None
        else trailing_average([h.capex_margin for h in historical_schedule], trailing_years),
        "nwc_margin": nwc_margin
        if nwc_margin is not None
        else trailing_average([h.nwc_margin for h in historical_schedule], trailing_years),
        "amortization_rate": amortization_rate if amortization_rate is not None else DEFAULT_AMORTIZATION_RATE,
        "revolver_limit": revolver_limit if revolver_limit is not None else default_revolver_limit(historical_debt),
        "interest_rate": interest_rate
        if interest_rate is not None
        else default_interest_rate(historical_debt, trailing_years),
        "tax_rate": tax_rate if tax_rate is not None else default_tax_rate(historical_linkage, trailing_years),
        "dividend_payout": dividend_payout if dividend_payout is not None else DEFAULT_DIVIDEND_PAYOUT,
        "balance_tolerance": balance_tolerance,
    }

    wb = Workbook()
    wb.remove(wb.active)

    cell_refs = _write_assumptions_sheet(wb, ticker, resolved)

    def A(key: str) -> str:
        return _assumption_ref("Assumptions", cell_refs, key)

    historical_sheet = wb.create_sheet("Historical")
    _write_historical_sheet(historical_sheet, ticker, statements)

    forecast = wb.create_sheet("Forecast")
    forecast["A1"] = f"FORECAST — {ticker}, {forecast_years}y, non-circular (interest on opening term debt)"
    forecast["A1"].font = Font(bold=True, size=14)
    forecast["A2"] = (
        "Every cell past the Base column is a formula referencing the previous "
        "column or the Assumptions sheet. See model/excel_export.py's module "
        "docstring for why this workbook covers the non-circular mode only."
    )
    forecast["A2"].font = Font(italic=True, color="FF555555")
    last_col_letter = get_column_letter(2 + forecast_years)
    forecast.merge_cells(f"A2:{last_col_letter}2")

    header_row = 4
    row_of: dict[str, int] = {}
    for offset, (key, _label) in enumerate(FORECAST_ROWS):
        row_of[key] = header_row + 1 + offset

    forecast.cell(row=header_row, column=1, value="Line item").font = HEADER_FONT
    forecast.cell(row=header_row, column=1).fill = HEADER_FILL
    last_hist = statements[-1].fiscal_year
    base_header = forecast.cell(row=header_row, column=2, value=f"Base ({last_hist})")
    base_header.font = HEADER_FONT
    base_header.fill = HEADER_FILL

    fiscal_year = last_hist
    fiscal_years: list[str] = []
    for _ in range(forecast_years):
        fiscal_year = next_fiscal_year(fiscal_year)
        fiscal_years.append(fiscal_year)
        col = 2 + len(fiscal_years)
        cell = forecast.cell(row=header_row, column=col, value=fiscal_year)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    for key, label in FORECAST_ROWS:
        cell = forecast.cell(row=row_of[key], column=1, value=label)
        cell.border = THIN_BOTTOM

    hl_last = historical_linkage[-1]
    hd_last = historical_debt[-1]
    seg_last = segments[-1]
    base_literals = {
        "domestic_revenue": seg_last.domestic_revenue,
        "export_revenue": seg_last.export_revenue,
        "term_debt": hd_last.total_debt,
        "net_working_capital": hl_last.net_working_capital,
        "revolver_balance": 0.0,
        "cash": hl_last.cash,
        "other_assets": hl_last.other_assets,
        "equity_and_other_liabilities": hl_last.equity_and_other_liabilities,
        "shares_outstanding": statements[-1].shares_outstanding,
    }
    B = "B"
    forecast.cell(row=row_of["fiscal_year"], column=2, value=last_hist)
    for key, value in base_literals.items():
        forecast.cell(row=row_of[key], column=2, value=value).fill = BASE_FILL
    forecast.cell(row=row_of["total_revenue"], column=2, value=f"={B}{row_of['domestic_revenue']}+{B}{row_of['export_revenue']}").fill = BASE_FILL
    forecast.cell(row=row_of["total_debt"], column=2, value=f"={B}{row_of['term_debt']}+{B}{row_of['revolver_balance']}").fill = BASE_FILL
    forecast.cell(row=row_of["total_assets"], column=2, value=f"={B}{row_of['cash']}+{B}{row_of['net_working_capital']}+{B}{row_of['other_assets']}").fill = BASE_FILL
    forecast.cell(row=row_of["total_liabilities_and_equity"], column=2, value=f"={B}{row_of['total_debt']}+{B}{row_of['equity_and_other_liabilities']}").fill = BASE_FILL

    for idx, fy in enumerate(fiscal_years):
        col = 3 + idx
        letter = get_column_letter(col)
        prev_letter = get_column_letter(col - 1)

        def r(key: str) -> int:
            return row_of[key]

        def cur(key: str) -> str:
            return f"{letter}{r(key)}"

        def prev(key: str) -> str:
            return f"{prev_letter}{r(key)}"

        f = forecast
        f.cell(row=r("fiscal_year"), column=col, value=fy)

        f.cell(row=r("domestic_revenue"), column=col, value=f"={prev('domestic_revenue')}*(1+{A('domestic_growth')})")
        f.cell(row=r("export_revenue"), column=col, value=f"={prev('export_revenue')}*(1+{A('export_growth')})")
        f.cell(row=r("total_revenue"), column=col, value=f"={cur('domestic_revenue')}+{cur('export_revenue')}")

        f.cell(row=r("ebitda_margin_used"), column=col, value=f"={A('ebitda_margin')}")
        f.cell(row=r("ebitda"), column=col, value=f"={cur('total_revenue')}*{cur('ebitda_margin_used')}")
        f.cell(row=r("da_margin_used"), column=col, value=f"={A('da_margin')}")
        f.cell(row=r("da"), column=col, value=f"={cur('total_revenue')}*{cur('da_margin_used')}")
        f.cell(row=r("ebit"), column=col, value=f"={cur('ebitda')}-{cur('da')}")

        f.cell(row=r("amortization_rate_used"), column=col, value=f"={A('amortization_rate')}")
        f.cell(
            row=r("scheduled_amortization"),
            column=col,
            value=f"=MIN({prev('term_debt')},{cur('amortization_rate_used')}*{prev('term_debt')})",
        )
        f.cell(row=r("term_debt"), column=col, value=f"={prev('term_debt')}-{cur('scheduled_amortization')}")

        f.cell(row=r("interest_rate_used"), column=col, value=f"={A('interest_rate')}")
        f.cell(row=r("interest_expense"), column=col, value=f"={cur('interest_rate_used')}*{prev('term_debt')}")

        f.cell(row=r("pretax_income"), column=col, value=f"={cur('ebit')}-{cur('interest_expense')}")
        f.cell(row=r("tax_rate_used"), column=col, value=f"={A('tax_rate')}")
        f.cell(row=r("tax_expense"), column=col, value=f"=MAX(0,{cur('tax_rate_used')}*{cur('pretax_income')})")
        f.cell(row=r("net_income"), column=col, value=f"={cur('pretax_income')}-{cur('tax_expense')}")
        f.cell(row=r("shares_outstanding"), column=col, value=f"={prev('shares_outstanding')}")
        f.cell(row=r("eps"), column=col, value=f"={cur('net_income')}*{LAKH_TO_RUPEES}/{cur('shares_outstanding')}")
        f.cell(row=r("dividend_payout_used"), column=col, value=f"={A('dividend_payout')}")
        f.cell(row=r("dividends"), column=col, value=f"={cur('dividend_payout_used')}*MAX({cur('net_income')},0)")
        f.cell(
            row=r("dividend_per_share"),
            column=col,
            value=f"={cur('dividends')}*{LAKH_TO_RUPEES}/{cur('shares_outstanding')}",
        )

        f.cell(row=r("capex_margin_used"), column=col, value=f"={A('capex_margin')}")
        f.cell(row=r("capex"), column=col, value=f"={cur('total_revenue')}*{cur('capex_margin_used')}")
        f.cell(row=r("nwc_margin_used"), column=col, value=f"={A('nwc_margin')}")
        f.cell(row=r("net_working_capital"), column=col, value=f"={cur('total_revenue')}*{cur('nwc_margin_used')}")
        f.cell(row=r("delta_nwc"), column=col, value=f"={cur('net_working_capital')}-{prev('net_working_capital')}")

        f.cell(
            row=r("cfads_after_tax"),
            column=col,
            value=f"={cur('ebitda')}-{cur('capex')}-{cur('delta_nwc')}-{cur('tax_expense')}",
        )
        f.cell(
            row=r("cash_before_revolver"),
            column=col,
            value=f"={cur('cfads_after_tax')}-{cur('scheduled_amortization')}-{cur('interest_expense')}",
        )

        f.cell(row=r("revolver_limit_used"), column=col, value=f"={A('revolver_limit')}")
        f.cell(
            row=r("revolver_draw"),
            column=col,
            value=(
                f"=IF({cur('cash_before_revolver')}>=0,0,"
                f"MIN(-{cur('cash_before_revolver')},MAX(0,{cur('revolver_limit_used')}-{prev('revolver_balance')})))"
            ),
        )
        f.cell(
            row=r("revolver_repayment"),
            column=col,
            value=f"=IF({cur('cash_before_revolver')}>=0,MIN({prev('revolver_balance')},{cur('cash_before_revolver')}),0)",
        )
        f.cell(
            row=r("revolver_balance"),
            column=col,
            value=f"={prev('revolver_balance')}+{cur('revolver_draw')}-{cur('revolver_repayment')}",
        )
        f.cell(
            row=r("unmet_financing_gap"),
            column=col,
            value=f"=IF({cur('cash_before_revolver')}>=0,0,(-{cur('cash_before_revolver')})-{cur('revolver_draw')})",
        )
        f.cell(row=r("total_debt"), column=col, value=f"={cur('term_debt')}+{cur('revolver_balance')}")

        f.cell(row=r("cfo"), column=col, value=f"={cur('net_income')}+{cur('da')}-{cur('delta_nwc')}")
        f.cell(row=r("cfi"), column=col, value=f"=-{cur('capex')}")
        f.cell(
            row=r("cff"),
            column=col,
            value=(
                f"=({cur('total_debt')}-({prev('term_debt')}+{prev('revolver_balance')}))-{cur('dividends')}"
            ),
        )
        f.cell(
            row=r("net_change_in_cash"),
            column=col,
            value=f"={cur('cfo')}+{cur('cfi')}+{cur('cff')}",
        )
        f.cell(row=r("cash"), column=col, value=f"={prev('cash')}+{cur('net_change_in_cash')}")
        f.cell(row=r("other_assets"), column=col, value=f"={prev('other_assets')}+{cur('capex')}-{cur('da')}")
        f.cell(
            row=r("equity_and_other_liabilities"),
            column=col,
            value=f"={prev('equity_and_other_liabilities')}+{cur('net_income')}-{cur('dividends')}",
        )
        f.cell(
            row=r("book_value_per_share"),
            column=col,
            value=f"={cur('equity_and_other_liabilities')}*{LAKH_TO_RUPEES}/{cur('shares_outstanding')}",
        )

        f.cell(
            row=r("total_assets"),
            column=col,
            value=f"={cur('cash')}+{cur('net_working_capital')}+{cur('other_assets')}",
        )
        f.cell(
            row=r("total_liabilities_and_equity"),
            column=col,
            value=f"={cur('total_debt')}+{cur('equity_and_other_liabilities')}",
        )
        f.cell(
            row=r("balance_difference"),
            column=col,
            value=f"={cur('total_assets')}-{cur('total_liabilities_and_equity')}",
        )
        f.cell(
            row=r("balance_check"),
            column=col,
            value=f'=IF(ABS({cur("balance_difference")})<={A("balance_tolerance")},"PASS","FAIL")',
        )

    forecast.column_dimensions["A"].width = 44
    for col in range(2, 3 + forecast_years):
        forecast.column_dimensions[get_column_letter(col)].width = 16
    forecast.freeze_panes = "C5"

    return wb


def export_workbook(
    ticker: str,
    statements: list[HistoricalStatement],
    segments: list[SegmentRevenue],
    forecast_years: int,
    output_path: Path,
    **kwargs,
) -> Path:
    wb = build_workbook(ticker, statements, segments, forecast_years, **kwargs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path

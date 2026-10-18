"""Day 1: ingest hand-entered historical financials into a normalized schema.

``data/<TICKER>/financials.csv`` is reused verbatim from reverse-dcf-engine's
own Day 2 transcription (see ``research/sources.md`` for why, and for where
the actual page citations live) — a flat, 14-column table, one row per fiscal
year. This module turns that flat table into three typed statement objects
per year (income statement, balance-sheet summary, cash-flow summary) rather
than passing the raw columns straight through, and checks the one thing a
flat CSV cannot: whether the numbers in it are internally consistent.

The balance-sheet and cash-flow objects are deliberately thin. The source
file has no liabilities/equity breakdown and no full cash-flow statement
(see ``research/sources.md``), so this schema only carries what is actually
present — ``total_equity`` is not a field here, not an omission to fix later
with a plug.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = [
    "fiscal_year",
    "revenue",
    "ebitda",
    "depreciation_amortization",
    "ebit",
    "interest_expense",
    "tax_expense",
    "net_profit",
    "total_assets",
    "total_debt",
    "cash_and_equivalents",
    "net_working_capital",
    "capex",
    "shares_outstanding",
]

LINE_ITEM_COLUMNS = REQUIRED_COLUMNS[1:]

# Both identities are tautologies by construction (reverse-dcf-engine derived
# ebit and ebitda this way from the two reported numbers, profit-before-tax
# and finance costs — see that repo's financials.py docstring), so a mismatch
# here means a transcription or copy slip, not a real accounting surprise.
IDENTITY_TOLERANCE = 0.05

LAKH_TO_RUPEES = 100_000
"""``financials.csv`` reports every rupee line item in ₹ lakh (confirmed in
``research/sources.md``); ``shares_outstanding`` is a raw share count, not
in lakh. A per-share metric (EPS, book value per share) has to multiply the
₹-lakh figure by this constant before dividing by shares, or the result
comes out in lakh-per-share — five orders of magnitude off. The same trap,
the same data, and the same fix as reverse-dcf-engine's own
``forward.LAKH_TO_RUPEES``."""


@dataclass(frozen=True)
class IncomeStatement:
    fiscal_year: str
    revenue: float
    ebitda: float
    depreciation_amortization: float
    ebit: float
    interest_expense: float
    tax_expense: float
    net_profit: float

    @property
    def pretax_income(self) -> float:
        return self.ebit - self.interest_expense

    @property
    def ebit_margin(self) -> float:
        return self.ebit / self.revenue

    @property
    def net_margin(self) -> float:
        return self.net_profit / self.revenue


@dataclass(frozen=True)
class BalanceSheetSummary:
    """Only what the source data actually has — see this module's docstring."""

    fiscal_year: str
    total_assets: float
    total_debt: float
    cash_and_equivalents: float
    net_working_capital: float

    @property
    def net_debt(self) -> float:
        return self.total_debt - self.cash_and_equivalents


@dataclass(frozen=True)
class CashFlowSummary:
    """Only what the source data actually has — see this module's docstring."""

    fiscal_year: str
    capex: float
    depreciation_amortization: float


@dataclass(frozen=True)
class HistoricalStatement:
    fiscal_year: str
    shares_outstanding: float
    income: IncomeStatement
    balance_sheet: BalanceSheetSummary
    cash_flow: CashFlowSummary

    @property
    def eps(self) -> float:
        """Basic EPS in rupees: ``income.net_profit`` (₹ lakh) converted to
        rupees via :data:`LAKH_TO_RUPEES`, divided by the raw share count."""
        return self.income.net_profit * LAKH_TO_RUPEES / self.shares_outstanding

    @property
    def book_value_per_share(self) -> float:
        """``total_assets - total_debt`` (₹ lakh — the same
        equity-and-other-liabilities approximation ``model.linkage``
        documents and uses, since no liabilities/equity breakdown exists
        in the source data) converted to rupees, divided by the raw share
        count.

        No ``dividend_per_share`` equivalent exists on this class:
        ``financials.csv`` has no dividend line at all for any historical
        year (see ``model.linkage``'s module docstring on
        ``DEFAULT_DIVIDEND_PAYOUT``), so there is no historical dividend
        figure to divide by shares in the first place.
        """
        equity_and_other_liabilities = self.balance_sheet.total_assets - self.balance_sheet.total_debt
        return equity_and_other_liabilities * LAKH_TO_RUPEES / self.shares_outstanding


def load_financials_csv(path: str | Path) -> pd.DataFrame:
    """Load the flat financials CSV and check the required columns are present."""
    df = pd.read_csv(path, dtype=str)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: financials.csv missing columns: {missing}")
    if df["fiscal_year"].duplicated().any():
        dupes = sorted(df.loc[df["fiscal_year"].duplicated(), "fiscal_year"].unique())
        raise ValueError(f"{path}: duplicate fiscal_year rows: {dupes}")
    return df


def to_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with every line-item column coerced to ``float``.

    Raises ``ValueError`` naming the offending column if a cell is not a
    plain number.
    """
    out = df.copy()
    for col in LINE_ITEM_COLUMNS:
        try:
            out[col] = out[col].astype(float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"non-numeric values in column '{col}': {exc}") from exc
    return out


def check_identities(df: pd.DataFrame, tolerance: float = IDENTITY_TOLERANCE) -> dict[str, list[str]]:
    """Return fiscal years where a derived-number identity fails.

    Two checks, both tautologies by construction if the CSV was transcribed
    correctly (see module docstring):

    - ``ebit_identity``: ``ebitda - depreciation_amortization == ebit``
    - ``net_profit_identity``: ``ebit - interest_expense - tax_expense == net_profit``
    """
    numeric = to_numeric(df)
    ebit_mismatches = []
    net_profit_mismatches = []
    for _, row in numeric.iterrows():
        implied_ebit = row["ebitda"] - row["depreciation_amortization"]
        if abs(implied_ebit - row["ebit"]) > tolerance:
            ebit_mismatches.append(row["fiscal_year"])

        implied_net_profit = row["ebit"] - row["interest_expense"] - row["tax_expense"]
        if abs(implied_net_profit - row["net_profit"]) > tolerance:
            net_profit_mismatches.append(row["fiscal_year"])
    return {"ebit_identity": ebit_mismatches, "net_profit_identity": net_profit_mismatches}


def load_historical_statements(path: str | Path) -> list[HistoricalStatement]:
    """Load, validate, and normalize ``financials.csv`` into one
    :class:`HistoricalStatement` per fiscal year, sorted earliest first.

    Raises ``ValueError`` if a required column is missing, a cell is
    non-numeric, or either identity check in :func:`check_identities` fails
    for any year — Day 1's "normalized schema" is meant to be trustworthy
    input for every later day, not a pass-through of whatever the CSV says.
    """
    df = load_financials_csv(path)
    numeric = to_numeric(df)

    failures = check_identities(numeric)
    broken = {name: years for name, years in failures.items() if years}
    if broken:
        detail = "; ".join(f"{name} fails for {years}" for name, years in broken.items())
        raise ValueError(f"{path}: identity check failed: {detail}")

    statements = [
        HistoricalStatement(
            fiscal_year=row["fiscal_year"],
            shares_outstanding=row["shares_outstanding"],
            income=IncomeStatement(
                fiscal_year=row["fiscal_year"],
                revenue=row["revenue"],
                ebitda=row["ebitda"],
                depreciation_amortization=row["depreciation_amortization"],
                ebit=row["ebit"],
                interest_expense=row["interest_expense"],
                tax_expense=row["tax_expense"],
                net_profit=row["net_profit"],
            ),
            balance_sheet=BalanceSheetSummary(
                fiscal_year=row["fiscal_year"],
                total_assets=row["total_assets"],
                total_debt=row["total_debt"],
                cash_and_equivalents=row["cash_and_equivalents"],
                net_working_capital=row["net_working_capital"],
            ),
            cash_flow=CashFlowSummary(
                fiscal_year=row["fiscal_year"],
                capex=row["capex"],
                depreciation_amortization=row["depreciation_amortization"],
            ),
        )
        for _, row in numeric.iterrows()
    ]
    return sorted(statements, key=lambda s: s.fiscal_year)

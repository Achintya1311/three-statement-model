"""Day 5: full three-statement linkage, with a balance-check assertion
that fails loudly for every forecast year.

The source data has no liabilities/equity breakdown and no full cash-flow
statement (``research/sources.md``, flagged as a Day 5 blocker since Day 1).
Two honest decompositions make a real linkage buildable from what the data
*does* have, rather than inventing the missing granularity:

- **Assets**, split into ``cash``, ``net_working_capital`` (both already
  columns) and ``other_assets`` (plug for everything else — net fixed
  assets and anything not in cash or NWC — computed once per historical
  year as ``total_assets - cash - net_working_capital``, not invented).
- **Liabilities + equity**, split into ``total_debt`` (already a column)
  and ``equity_and_other_liabilities`` (``total_assets - total_debt``).
  This bucket folds every non-debt liability — trade payables,
  provisions, deferred tax — into "equity", the same simplification
  reverse-dcf-engine's own ``capital_structure()`` already made and
  documented for this same company, for the same reason: no breakdown
  exists to split them honestly. It real-understates liabilities (so
  overstates "equity"), flagged here and there alike.

Both decompositions are read directly off the real historical columns —
nothing here is solved for after the fact to make a number balance. The
forecast then rolls each bucket forward independently (assets from the
cash-flow statement and a capex/D&A roll-forward; liabilities+equity from
the debt schedule and retained earnings) and the balance check compares
the two sides. If the plumbing is wired correctly the two sides are the
same number by double-entry construction — the identity is not proof the
model is right, it is a trap for a *wiring* bug (a schedule's output not
actually flowing into both the asset and the liability side), and it
fails loudly, not silently, when one is forgotten. See the Traps section
of this project's own NEXT_STEPS.md: "a plug labelled 'balancing figure'
is a confession" — this module never backs into a number to make the
check pass.

**Two circularities, not one.** Day 4 already resolves interest-vs-average
-debt-balance circularity. Full linkage adds a second: cash tax depends on
pretax income, which is EBIT minus interest expense, which depends on the
debt schedule, which depends on CFADS, which (now) is *after* cash tax.
Each forecast year is solved with an outer fixed-point loop (tax guess ->
interest from one year of ``forecast_debt_schedule`` -> new tax -> ...)
wrapped around Day 4's own inner circularity, carrying the ending term
debt and revolver balance forward to seed the next year's opening balance
(the ``initial_revolver`` parameter debt_schedule.py gained for exactly
this). A year that does not converge is reported, not hidden, the same
posture Day 4 already took for its own circularity.

**What is still assumed, not derived, and flagged as such:**

- **Dividends.** ``financials.csv`` has no dividend line at all, so a real
  payout ratio cannot be derived from this data (not even imperfectly).
  ``DEFAULT_DIVIDEND_PAYOUT = 0.0`` (100% retained) is an explicit,
  overridable assumption, not a fact — a real dividend-paying company
  would show slower book-equity growth than this model projects.
- **Cash tax is floored at zero.** No loss-carryforward or tax-credit
  mechanics are modeled; a forecast year with negative pretax income
  would otherwise imply a tax refund this module does not attempt to
  model realistically.
- **The effective tax rate** is derived, like Day 4's interest rate: the
  real historical ``tax_expense / pretax_income`` per year, trailing-
  averaged (same pattern, same ``trailing_years`` default), overridable.
"""

from __future__ import annotations

from dataclasses import dataclass

from model.debt_schedule import (
    DEFAULT_AMORTIZATION_RATE,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_TOLERANCE,
    HistoricalDebtYear,
    build_historical_debt_schedule,
    default_interest_rate,
    default_revolver_limit,
    forecast_debt_schedule,
)
from model.historical import LAKH_TO_RUPEES, HistoricalStatement
from model.revenue_driver import SegmentRevenue, forecast_revenue
from model.schedules import (
    DEFAULT_TRAILING_YEARS,
    ForecastScheduleYear,
    build_schedule,
    forecast_schedule,
    trailing_average,
)

DEFAULT_DIVIDEND_PAYOUT = 0.0
DEFAULT_BALANCE_TOLERANCE = 0.01

TAX_RATE_BOUNDS = (0.0, 1.0)
DIVIDEND_PAYOUT_BOUNDS = (0.0, 1.0)
"""Valid ranges for ``tax_rate``/``dividend_payout`` overrides (P59):
both are fractions of pretax income/net income, so neither can honestly
be negative or exceed 1 -- e.g. a payout of 5 (500%) would otherwise pay
out five times net income and drive total assets and equity negative
while the balance check still reports "passed" (the two sides still agree
by construction; see ``ForecastLinkageYear.balance_check_passed``)."""
"""Absolute tolerance in the source data's own units (Rs. Lakh) for the
balance-check assertion. The linkage is an exact algebraic identity when
wired correctly (see module docstring) — this only absorbs floating-point
accumulation, not a real discrepancy."""


@dataclass(frozen=True)
class HistoricalLinkageYear:
    fiscal_year: str
    cash: float
    net_working_capital: float
    other_assets: float
    """``total_assets - cash - net_working_capital`` — everything else on
    the balance sheet (principally net fixed assets), not a plug solved
    for after the fact: every term on the right is a real column."""
    total_debt: float
    equity_and_other_liabilities: float
    """``total_assets - total_debt`` — see module docstring: folds every
    non-debt liability into "equity" because no breakdown exists to split
    them, the same approximation reverse-dcf-engine already made."""
    total_assets: float
    pretax_income: float
    tax_expense: float
    effective_tax_rate: float | None
    """``tax_expense / pretax_income``, or ``None`` when ``pretax_income``
    is not positive (the ratio is not meaningful there)."""


def build_historical_linkage(statements: list[HistoricalStatement]) -> list[HistoricalLinkageYear]:
    """One :class:`HistoricalLinkageYear` per fiscal year, sorted earliest first."""
    years = []
    for s in sorted(statements, key=lambda s: s.fiscal_year):
        bs = s.balance_sheet
        other_assets = bs.total_assets - bs.cash_and_equivalents - bs.net_working_capital
        equity_and_other_liabilities = bs.total_assets - bs.total_debt
        pretax_income = s.income.ebit - s.income.interest_expense
        effective_tax_rate = s.income.tax_expense / pretax_income if pretax_income > 0 else None
        years.append(
            HistoricalLinkageYear(
                fiscal_year=s.fiscal_year,
                cash=bs.cash_and_equivalents,
                net_working_capital=bs.net_working_capital,
                other_assets=other_assets,
                total_debt=bs.total_debt,
                equity_and_other_liabilities=equity_and_other_liabilities,
                total_assets=bs.total_assets,
                pretax_income=pretax_income,
                tax_expense=s.income.tax_expense,
                effective_tax_rate=effective_tax_rate,
            )
        )
    return years


def default_tax_rate(
    historical: list[HistoricalLinkageYear], trailing_years: int = DEFAULT_TRAILING_YEARS
) -> float:
    """Trailing average of the implied historical effective tax rate.

    Excludes any year with non-positive pretax income (no meaningful rate).
    """
    rates = [h.effective_tax_rate for h in historical if h.effective_tax_rate is not None]
    if not rates:
        raise ValueError("need at least one historical year with positive pretax income to imply a tax rate")
    return trailing_average(rates, trailing_years)


@dataclass(frozen=True)
class ForecastLinkageYear:
    fiscal_year: str
    revenue: float
    ebitda: float
    depreciation_amortization: float
    ebit: float
    interest_expense: float
    tax_expense: float
    net_income: float
    dividends: float
    capex: float
    delta_nwc: float
    scheduled_amortization: float
    revolver_draw: float
    revolver_repayment: float
    ending_total_debt: float
    cash: float
    net_working_capital: float
    other_assets: float
    total_assets: float
    equity_and_other_liabilities: float
    total_liabilities_and_equity: float
    balance_difference: float
    """``total_assets - total_liabilities_and_equity``. Should be ~0 for a
    correctly wired linkage — see module docstring."""
    balance_check_passed: bool
    """Whether the two sides agree to within tolerance — a *wiring*
    identity, not a financing-feasibility check. It can be ``True`` even
    in a year with a positive ``unmet_financing_gap``: a shortfall the
    revolver limit couldn't cover still shows up correctly on both sides
    (as a lower cash balance on assets, with liabilities+equity unchanged
    by financing that was never actually available), so the two sides
    still agree by construction. ``unmet_financing_gap`` is the separate
    field that reports whether the company could actually fund itself —
    check it explicitly; a passing balance check alone does not mean the
    financing gap was zero."""
    unmet_financing_gap: float
    """Pass-through of :class:`model.debt_schedule.ForecastDebtYear`'s own
    field for this year: the cash shortfall the revolver limit could not
    cover, >= 0. Previously computed by the debt schedule and then
    discarded here — a real financing gap was silently folded into a
    lower (possibly negative) ``cash`` balance with nothing naming it.
    Surfaced explicitly so a caller never has to infer a financing gap
    from a negative cash balance after the fact."""
    debt_converged: bool
    """Day 4's own interest-vs-average-balance circularity, for this year."""
    tax_converged: bool
    """The outer tax-vs-interest circularity this module adds, for this year."""
    shares_outstanding: float
    """Held flat at the last historical year's own value for every forecast
    year — no corporate action (bonus issue, split, buyback, rights issue)
    is modeled anywhere in this repo (P31). Explicit and checkable here,
    rather than an assumption a caller has to infer from its absence."""
    eps: float
    """``net_income`` (₹ lakh, like every other figure on this dataclass)
    converted to rupees via :data:`model.historical.LAKH_TO_RUPEES`, divided
    by ``shares_outstanding``."""
    dividend_per_share: float
    """``dividends`` converted to rupees, divided by ``shares_outstanding``."""
    book_value_per_share: float
    """``equity_and_other_liabilities`` (this year's ending balance)
    converted to rupees, divided by ``shares_outstanding``."""


def forecast_full_linkage(
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
    circular: bool = True,
    trailing_years: int = DEFAULT_TRAILING_YEARS,
    balance_tolerance: float = DEFAULT_BALANCE_TOLERANCE,
    max_tax_iterations: int = DEFAULT_MAX_ITERATIONS,
    tax_tolerance: float = DEFAULT_TOLERANCE,
) -> list[ForecastLinkageYear]:
    """Project all three statements forward, linked, one
    :class:`ForecastLinkageYear` per forecast year.

    Chains onto Day 2's revenue forecast and Day 3's EBITDA/D&A/capex/NWC
    schedule (both re-derived here exactly as Day 3/4's own CLIs do, never
    re-implemented) and Day 4's debt schedule, called one year at a time so
    this module's own tax-vs-interest circularity (see module docstring)
    can be resolved before the next year's opening balances are fixed.

    ``domestic_growth``/``export_growth`` and the four margin overrides pass
    straight through to Day 2's ``forecast_revenue`` and Day 3's
    ``forecast_schedule`` — the same override-the-driver flags those CLIs
    already expose individually (``model.revenue``, ``model.costs``), not
    re-derived here. Day 6's Excel export computes these two forecasts
    directly for the same reason (non-circular scope); Day 7's sensitivity
    CLI is the first caller that needs to swing them through the full
    circular linkage, which is why this function gained them rather than
    each caller reaching into ``model.revenue_driver``/``model.schedules``
    itself.
    """
    if not statements:
        raise ValueError("need at least one historical statement")
    if forecast_years < 1:
        raise ValueError("forecast_years must be >= 1")

    schedule = build_schedule(statements)
    revenue_forecasts = forecast_revenue(
        segments, forecast_years, domestic_growth=domestic_growth, export_growth=export_growth
    )
    cost_forecasts = forecast_schedule(
        schedule,
        revenue_forecasts,
        ebitda_margin=ebitda_margin,
        da_margin=da_margin,
        capex_margin=capex_margin,
        nwc_margin=nwc_margin,
        trailing_years=trailing_years,
    )

    return forecast_linkage_from_cost_forecasts(
        statements,
        cost_forecasts,
        tax_rate=tax_rate,
        dividend_payout=dividend_payout,
        amortization_rate=amortization_rate,
        revolver_limit=revolver_limit,
        interest_rate=interest_rate,
        circular=circular,
        trailing_years=trailing_years,
        balance_tolerance=balance_tolerance,
        max_tax_iterations=max_tax_iterations,
        tax_tolerance=tax_tolerance,
    )


def forecast_linkage_from_cost_forecasts(
    statements: list[HistoricalStatement],
    cost_forecasts: list[ForecastScheduleYear],
    tax_rate: float | None = None,
    dividend_payout: float | None = None,
    amortization_rate: float | None = None,
    revolver_limit: float | None = None,
    interest_rate: float | None = None,
    circular: bool = True,
    trailing_years: int = DEFAULT_TRAILING_YEARS,
    balance_tolerance: float = DEFAULT_BALANCE_TOLERANCE,
    max_tax_iterations: int = DEFAULT_MAX_ITERATIONS,
    tax_tolerance: float = DEFAULT_TOLERANCE,
) -> list[ForecastLinkageYear]:
    """The per-year tax/interest circularity loop :func:`forecast_full_linkage`
    runs, pulled out so a caller that needs a *different* revenue/cost
    forecast per year — Day 8's revolver-draw scenario
    (``model.revolver_scenario``), which forecasts some years at baseline
    assumptions and others under a deliberate shock — can drive this same,
    already-tested loop with its own :class:`model.schedules.ForecastScheduleYear`
    list instead of the single flat set of overrides
    :func:`forecast_full_linkage` builds one ``cost_forecasts`` from.

    ``cost_forecasts`` must be in fiscal-year order, immediately following
    ``statements``' last historical year — the same shape
    :func:`forecast_full_linkage` already passes in.
    """
    if not statements:
        raise ValueError("need at least one historical statement")
    if not cost_forecasts:
        raise ValueError("need at least one forecast year")
    for flag, value, (lo, hi) in (
        ("tax_rate", tax_rate, TAX_RATE_BOUNDS),
        ("dividend_payout", dividend_payout, DIVIDEND_PAYOUT_BOUNDS),
    ):
        if value is not None and not (lo <= value <= hi):
            raise ValueError(f"{flag}={value!r} is outside the allowed range [{lo}, {hi}]")

    historical_linkage = build_historical_linkage(statements)
    historical_debt = build_historical_debt_schedule(statements)

    used_amortization_rate = amortization_rate if amortization_rate is not None else DEFAULT_AMORTIZATION_RATE
    used_revolver_limit = (
        revolver_limit if revolver_limit is not None else default_revolver_limit(historical_debt)
    )
    used_interest_rate = (
        interest_rate if interest_rate is not None else default_interest_rate(historical_debt, trailing_years)
    )
    used_tax_rate = tax_rate if tax_rate is not None else default_tax_rate(historical_linkage, trailing_years)
    used_dividend_payout = dividend_payout if dividend_payout is not None else DEFAULT_DIVIDEND_PAYOUT

    last = historical_linkage[-1]
    cash = last.cash
    other_assets = last.other_assets
    equity_and_other_liabilities = last.equity_and_other_liabilities
    opening_term_debt = historical_debt[-1].total_debt
    opening_revolver = 0.0
    shares_outstanding = sorted(statements, key=lambda s: s.fiscal_year)[-1].shares_outstanding

    forecasts = []
    for cost_year in cost_forecasts:
        interest_guess = 0.0
        debt_result = None
        tax_converged = False
        for _ in range(max_tax_iterations):
            pretax_income = cost_year.ebit - interest_guess
            tax_expense = max(0.0, used_tax_rate * pretax_income)
            cfads_after_tax = cost_year.ebitda - cost_year.capex - cost_year.delta_nwc - tax_expense

            single_year_historical = [
                HistoricalDebtYear(
                    fiscal_year="<carried forward>",
                    total_debt=opening_term_debt,
                    interest_expense=0.0,
                    implied_interest_rate=None,
                )
            ]
            debt_result = forecast_debt_schedule(
                single_year_historical,
                [cost_year.fiscal_year],
                [cfads_after_tax],
                amortization_rate=used_amortization_rate,
                revolver_limit=used_revolver_limit,
                interest_rate=used_interest_rate,
                circular=circular,
                initial_revolver=opening_revolver,
            )[0]

            new_interest = debt_result.interest_expense
            if abs(new_interest - interest_guess) < tax_tolerance:
                interest_guess = new_interest
                tax_converged = True
                break
            interest_guess = new_interest
        else:
            tax_converged = False

        interest_expense = debt_result.interest_expense
        pretax_income = cost_year.ebit - interest_expense
        tax_expense = max(0.0, used_tax_rate * pretax_income)
        net_income = pretax_income - tax_expense
        dividends = used_dividend_payout * max(net_income, 0.0)

        ending_total_debt = debt_result.ending_total_debt
        opening_total_debt = opening_term_debt + opening_revolver
        debt_delta = ending_total_debt - opening_total_debt

        cfo = net_income + cost_year.depreciation_amortization - cost_year.delta_nwc
        cfi = -cost_year.capex
        cff = debt_delta - dividends
        new_cash = cash + cfo + cfi + cff
        new_other_assets = other_assets + cost_year.capex - cost_year.depreciation_amortization
        new_equity_and_other_liabilities = equity_and_other_liabilities + net_income - dividends

        total_assets = new_cash + cost_year.net_working_capital + new_other_assets
        total_liabilities_and_equity = ending_total_debt + new_equity_and_other_liabilities
        balance_difference = total_assets - total_liabilities_and_equity

        eps = net_income * LAKH_TO_RUPEES / shares_outstanding
        dividend_per_share = dividends * LAKH_TO_RUPEES / shares_outstanding
        book_value_per_share = new_equity_and_other_liabilities * LAKH_TO_RUPEES / shares_outstanding

        forecasts.append(
            ForecastLinkageYear(
                fiscal_year=cost_year.fiscal_year,
                revenue=cost_year.revenue,
                ebitda=cost_year.ebitda,
                depreciation_amortization=cost_year.depreciation_amortization,
                ebit=cost_year.ebit,
                interest_expense=interest_expense,
                tax_expense=tax_expense,
                net_income=net_income,
                dividends=dividends,
                capex=cost_year.capex,
                delta_nwc=cost_year.delta_nwc,
                scheduled_amortization=debt_result.scheduled_amortization,
                revolver_draw=debt_result.revolver_draw,
                revolver_repayment=debt_result.revolver_repayment,
                ending_total_debt=ending_total_debt,
                cash=new_cash,
                net_working_capital=cost_year.net_working_capital,
                other_assets=new_other_assets,
                total_assets=total_assets,
                equity_and_other_liabilities=new_equity_and_other_liabilities,
                total_liabilities_and_equity=total_liabilities_and_equity,
                balance_difference=balance_difference,
                balance_check_passed=abs(balance_difference) <= balance_tolerance,
                unmet_financing_gap=debt_result.unmet_financing_gap,
                debt_converged=debt_result.converged,
                tax_converged=tax_converged,
                shares_outstanding=shares_outstanding,
                eps=eps,
                dividend_per_share=dividend_per_share,
                book_value_per_share=book_value_per_share,
            )
        )

        cash = new_cash
        other_assets = new_other_assets
        equity_and_other_liabilities = new_equity_and_other_liabilities
        opening_term_debt = debt_result.ending_term_debt
        opening_revolver = debt_result.ending_revolver

    return forecasts


def assert_balance_sheet_balances(
    forecasts: list[ForecastLinkageYear], tolerance: float = DEFAULT_BALANCE_TOLERANCE
) -> None:
    """Fail loudly, naming every offending year, if assets != liabilities +
    equity for any forecast year — the Day 5 "done when" gate.

    Deliberately recomputes the difference from ``total_assets`` and
    ``total_liabilities_and_equity`` rather than trusting each year's own
    stored ``balance_difference``/``balance_check_passed`` fields (which
    could, in principle, have been computed against a different tolerance
    or gone stale against a mutated year), so this assertion's pass/fail
    is never silently decided somewhere else.
    """
    failures = []
    for f in forecasts:
        diff = f.total_assets - f.total_liabilities_and_equity
        if abs(diff) > tolerance:
            failures.append((f, diff))
    if failures:
        detail = "; ".join(
            f"{f.fiscal_year}: assets {f.total_assets:,.2f} != liabilities+equity "
            f"{f.total_liabilities_and_equity:,.2f} (diff {diff:,.2f})"
            for f, diff in failures
        )
        raise AssertionError(f"balance sheet does not balance for every forecast year: {detail}")


def to_fundamentals_contract(
    statements: list[HistoricalStatement],
    forecasts: list[ForecastLinkageYear],
    *,
    dividend_payout: float | None = None,
    amortization_rate: float | None = None,
    revolver_limit: float | None = None,
) -> dict:
    """The ``fundamentals`` block this repo publishes to the spine (v0.8):
    FY3 revenue CAGR off the last historical year, FY3 EBIT margin, FY3 net
    debt/EBITDA, and whether the balance check
    (:func:`assert_balance_sheet_balances`) passed for every forecast year —
    the exact shape ``NEXT_STEPS.md`` committed to before this function
    existed — plus, additively (D48), ``base_fiscal_year`` (the last
    historical year) and ``fy3_fiscal_year`` (the third forecast year). Requires at least 3 forecast years; the CLI's own
    ``--forecast-years`` default already satisfies this.

    P100: ``dividend_payout`` is the payout the forecast ran at, and
    ``assumed_inputs`` names every input left at a default that the filings
    do not supply (no dividend data, no loan schedule, no facility size).
    Pass the same overrides the forecast used; an overridden input drops
    off the list.
    """
    if not statements:
        raise ValueError("need at least one historical statement for the base-year revenue")
    if len(forecasts) < 3:
        raise ValueError(f"fy3 contract needs at least 3 forecast years, got {len(forecasts)}")

    base_revenue = statements[-1].income.revenue
    fy3 = forecasts[2]
    try:
        assert_balance_sheet_balances(forecasts)
        balance_check = "passed"
    except AssertionError:
        balance_check = "failed"

    return {
        "fundamentals": {
            "fy3_revenue_cagr": (fy3.revenue / base_revenue) ** (1 / 3) - 1,
            "fy3_ebit_margin": fy3.ebit / fy3.revenue,
            "net_debt_ebitda_fy3": (fy3.ending_total_debt - fy3.cash) / fy3.ebitda,
            "balance_check": balance_check,
            # D48: the fy3 figures are a forecast; name the years they span.
            "base_fiscal_year": statements[-1].fiscal_year,
            "fy3_fiscal_year": fy3.fiscal_year,
            # P100: what the figures rest on that no filing supplies (additive).
            "dividend_payout": dividend_payout if dividend_payout is not None else DEFAULT_DIVIDEND_PAYOUT,
            "assumed_inputs": [
                text
                for value, text in (
                    (dividend_payout, f"dividend_payout {DEFAULT_DIVIDEND_PAYOUT:.0%} (no dividend data in the financials)"),
                    (amortization_rate, f"amortization_rate {DEFAULT_AMORTIZATION_RATE:.0%}/yr (no loan schedule disclosed)"),
                    (revolver_limit, "revolver_limit = peak historical total debt (no facility size disclosed)"),
                )
                if value is None
            ],
        }
    }

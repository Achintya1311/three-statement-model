"""Day 4: debt schedule — mandatory amortization, revolver, cash sweep,
interest on average debt behind an explicit circularity toggle.

The source data (``data/<ticker>/financials.csv``) carries only one
debt figure per year, ``total_debt`` — no split between term debt and a
revolving facility, no disclosed amortization schedule, no stated interest
rate, and no revolver facility size. Three assumptions have to be made
honestly rather than invented silently, and each is a named, overridable
parameter rather than a hardcoded number buried in a formula:

- **Amortization rate** (``DEFAULT_AMORTIZATION_RATE``): no loan agreement
  is disclosed, so there is no real schedule to transcribe. Historical
  ``total_debt`` is treated as the opening term-debt balance and amortized
  at a flat, illustrative rate of its opening balance each forecast year —
  a declining-balance assumption, not a fact pulled from a filing.
- **Revolver limit** (``DEFAULT_REVOLVER_LIMIT_FACTOR``): no facility size
  is disclosed either. Defaults to the historical peak ``total_debt``,
  the closest honest proxy for "however much debt this company has
  actually carried before" — flagged as an assumption, not a covenant.
- **Interest rate**: unlike the two above, this one *is* derivable from
  the data — ``interest_expense / average(total_debt)`` for each
  historical year is a real implied effective rate, not invented. It
  defaults to the trailing average of those implied rates (the same
  override-the-driver pattern Day 3 used for margins), overridable like
  everything else here.

**The circularity, and the toggle.** Interest computed on the *average*
of a year's opening and closing debt balance is standard practice (it
does not overstate interest when debt is paid down intra-year), but it
is circular: the closing balance depends on how much cash is left to pay
down the revolver, which depends on interest expense, which depends on
the closing balance. ``circular=True`` resolves this with fixed-point
iteration (recompute interest from the latest average balance, resolve
the revolver sweep against it, repeat until the interest estimate stops
moving, bounded by ``max_iterations``); a run that does not converge is
reported as such (``converged=False``) rather than silently accepted.
``circular=False`` breaks the loop by charging interest on the *opening*
balance only — a one-pass approximation that understates interest in a
paydown year and overstates it in a draw year, traded for not iterating.

**What this module does not do.** It takes a year's cash available for
debt service (``cash_available_for_debt_service``) as a plain input list
rather than deriving it from the full income statement — that full
linkage, including the second circularity between interest expense and
the cash taxes it shields, is Day 5's job. The CLI (``model/debt.py``)
chains onto Day 3's EBITDA/capex/working-capital forecast with an
explicit pre-tax, pre-interest proxy, documented there and in this
project's README Limitations as a simplification Day 5 will supersede.
"""

from __future__ import annotations

from dataclasses import dataclass

from model.historical import HistoricalStatement
from model.schedules import DEFAULT_TRAILING_YEARS, trailing_average

DEFAULT_AMORTIZATION_RATE = 0.10
DEFAULT_MAX_ITERATIONS = 50
DEFAULT_TOLERANCE = 1e-6

MIN_AMORTIZATION_RATE = 0.0
"""Floor for an ``amortization_rate`` override (P59): a negative rate
means debt *growing* on its own every year under a flag named for paying
it down, the real defect P59 found (``--amort-rate -0.5``). No upper
bound: a rate over 1 is already handled correctly and deliberately
tested (``scheduled_amortization`` is capped at the opening balance via
``min()`` below, see ``test_forecast_debt_schedule_amortization_never_
exceeds_the_opening_balance``), so it is a harmless, not a degenerate,
input."""


@dataclass(frozen=True)
class HistoricalDebtYear:
    fiscal_year: str
    total_debt: float
    interest_expense: float
    implied_interest_rate: float | None
    """``interest_expense / average(prior total_debt, this total_debt)``.
    ``None`` for the first historical year, which has no prior balance to
    average against."""


def build_historical_debt_schedule(statements: list[HistoricalStatement]) -> list[HistoricalDebtYear]:
    """One :class:`HistoricalDebtYear` per fiscal year, sorted earliest first."""
    years = []
    prior_debt: float | None = None
    for s in sorted(statements, key=lambda s: s.fiscal_year):
        total_debt = s.balance_sheet.total_debt
        if prior_debt is None:
            implied_rate = None
        else:
            implied_rate = s.income.interest_expense / ((prior_debt + total_debt) / 2)
        years.append(
            HistoricalDebtYear(
                fiscal_year=s.fiscal_year,
                total_debt=total_debt,
                interest_expense=s.income.interest_expense,
                implied_interest_rate=implied_rate,
            )
        )
        prior_debt = total_debt
    return years


def default_interest_rate(
    historical: list[HistoricalDebtYear], trailing_years: int = DEFAULT_TRAILING_YEARS
) -> float:
    """Trailing average of the implied historical effective interest rate.

    Excludes the first historical year, which has no implied rate (no
    prior balance to average against).
    """
    rates = [h.implied_interest_rate for h in historical if h.implied_interest_rate is not None]
    if not rates:
        raise ValueError("need at least two historical years to imply an interest rate")
    return trailing_average(rates, trailing_years)


def default_revolver_limit(historical: list[HistoricalDebtYear]) -> float:
    """Historical peak ``total_debt`` — see module docstring for why this,
    not a disclosed facility size, is the assumption used."""
    return max(h.total_debt for h in historical)


@dataclass(frozen=True)
class ForecastDebtYear:
    fiscal_year: str
    opening_term_debt: float
    scheduled_amortization: float
    ending_term_debt: float
    opening_revolver: float
    revolver_draw: float
    revolver_repayment: float
    ending_revolver: float
    ending_total_debt: float
    interest_expense: float
    interest_rate_used: float
    cash_after_debt_service: float
    """Cash left over after amortization, interest and the revolver sweep.
    Positive when debt service was fully covered with cash to spare;
    negative only when ``unmet_financing_gap`` is also positive (the
    revolver limit was not enough to cover the shortfall)."""
    unmet_financing_gap: float
    """Cash shortfall the revolver limit could not cover, >= 0. A positive
    value is a real financing gap this schedule reports rather than
    hides — it is not plugged with invented equity or debt capacity."""
    converged: bool
    iterations: int


def _resolve_revolver(
    cash_before_revolver: float, opening_revolver: float, revolver_limit: float
) -> tuple[float, float, float, float, float]:
    """One pass of the cash sweep / revolver draw against a known
    ``cash_before_revolver`` (CFADS minus amortization minus interest).

    Returns ``(revolver_draw, revolver_repayment, ending_revolver,
    cash_after_debt_service, unmet_financing_gap)``.
    """
    if cash_before_revolver >= 0:
        revolver_repayment = min(opening_revolver, cash_before_revolver)
        ending_revolver = opening_revolver - revolver_repayment
        cash_after = cash_before_revolver - revolver_repayment
        return 0.0, revolver_repayment, ending_revolver, cash_after, 0.0

    shortfall = -cash_before_revolver
    available_capacity = max(0.0, revolver_limit - opening_revolver)
    revolver_draw = min(shortfall, available_capacity)
    ending_revolver = opening_revolver + revolver_draw
    unmet = shortfall - revolver_draw
    cash_after = -unmet
    return revolver_draw, 0.0, ending_revolver, cash_after, unmet


def forecast_debt_schedule(
    historical: list[HistoricalDebtYear],
    fiscal_years: list[str],
    cash_available_for_debt_service: list[float],
    amortization_rate: float | None = None,
    revolver_limit: float | None = None,
    interest_rate: float | None = None,
    circular: bool = True,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tolerance: float = DEFAULT_TOLERANCE,
    trailing_years: int = DEFAULT_TRAILING_YEARS,
    initial_revolver: float = 0.0,
) -> list[ForecastDebtYear]:
    """Project the debt schedule forward, one :class:`ForecastDebtYear` per
    entry in ``fiscal_years`` / ``cash_available_for_debt_service`` (same
    order, same length).

    ``cash_available_for_debt_service`` (CFADS) is cash available *before*
    scheduled amortization and interest for that year — see the module
    docstring for why this is a plain input here rather than derived from
    a full income statement. The opening term-debt balance is the last
    historical year's ``total_debt``; the opening revolver balance is
    ``initial_revolver`` (default ``0.0`` — no revolver usage is evidenced
    in the historical data, see this project's README Limitations).
    ``initial_revolver`` exists so Day 5's full linkage can carry a
    revolver balance across separate, single-year calls to this function
    (it resolves its own interest/tax circularity one year at a time) —
    calling with the whole forecast horizon in one list, as Day 4's own
    CLI does, never needs it and keeps passing the default.
    """
    if not historical:
        raise ValueError("need at least one historical debt year")
    if not fiscal_years:
        raise ValueError("need at least one forecast year")
    if len(fiscal_years) != len(cash_available_for_debt_service):
        raise ValueError("fiscal_years and cash_available_for_debt_service must be the same length")
    if amortization_rate is not None and amortization_rate < MIN_AMORTIZATION_RATE:
        raise ValueError(f"amortization_rate={amortization_rate!r} must be >= {MIN_AMORTIZATION_RATE}")

    used_amortization_rate = amortization_rate if amortization_rate is not None else DEFAULT_AMORTIZATION_RATE
    used_revolver_limit = revolver_limit if revolver_limit is not None else default_revolver_limit(historical)
    used_interest_rate = (
        interest_rate if interest_rate is not None else default_interest_rate(historical, trailing_years)
    )

    opening_term_debt = historical[-1].total_debt
    opening_revolver = initial_revolver
    forecasts = []
    for fiscal_year, cfads in zip(fiscal_years, cash_available_for_debt_service):
        scheduled_amortization = min(opening_term_debt, used_amortization_rate * opening_term_debt)
        ending_term_debt = opening_term_debt - scheduled_amortization

        if circular:
            interest_expense = used_interest_rate * opening_term_debt
            converged = False
            iterations = 0
            for iterations in range(1, max_iterations + 1):
                cash_before_revolver = cfads - scheduled_amortization - interest_expense
                draw, repay, ending_revolver, cash_after, unmet = _resolve_revolver(
                    cash_before_revolver, opening_revolver, used_revolver_limit
                )
                avg_total_debt = (
                    (opening_term_debt + opening_revolver) + (ending_term_debt + ending_revolver)
                ) / 2
                new_interest_expense = used_interest_rate * avg_total_debt
                if abs(new_interest_expense - interest_expense) < tolerance:
                    interest_expense = new_interest_expense
                    converged = True
                    break
                interest_expense = new_interest_expense
        else:
            interest_expense = used_interest_rate * opening_term_debt
            cash_before_revolver = cfads - scheduled_amortization - interest_expense
            draw, repay, ending_revolver, cash_after, unmet = _resolve_revolver(
                cash_before_revolver, opening_revolver, used_revolver_limit
            )
            converged = True
            iterations = 1

        forecasts.append(
            ForecastDebtYear(
                fiscal_year=fiscal_year,
                opening_term_debt=opening_term_debt,
                scheduled_amortization=scheduled_amortization,
                ending_term_debt=ending_term_debt,
                opening_revolver=opening_revolver,
                revolver_draw=draw,
                revolver_repayment=repay,
                ending_revolver=ending_revolver,
                ending_total_debt=ending_term_debt + ending_revolver,
                interest_expense=interest_expense,
                interest_rate_used=used_interest_rate,
                cash_after_debt_service=cash_after,
                unmet_financing_gap=unmet,
                converged=converged,
                iterations=iterations,
            )
        )
        opening_term_debt = ending_term_debt
        opening_revolver = ending_revolver

    return forecasts

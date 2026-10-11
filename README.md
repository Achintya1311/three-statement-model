# Three-statement model from primary filings

A fully linked income statement, balance sheet and cash flow forecast built from the filings with no template underneath, where the balance check is a test that fails loudly.

**Status:** Last checkpoint 2026-10-11 · Next: Day 4 - debt schedule: mandatory amortization, revolver, cash sweep, interest on average debt with an explicit circularity toggle

## What this is

Revenue is built from operating drivers rather than a growth percentage. Debt carries a real schedule with mandatory amortisation, a revolver and interest on average debt behind an explicit circularity toggle.

Exports to Excel with live formulas and assumptions in one marked block, because a workbook of pasted values cannot be interrogated.

## Correctness gate

pytest asserts assets = liabilities + equity across every forecast year with no unexplainable plug, and the workbook opens with live formulas.

This is the test that decides whether the repo is finished. A result that has not passed it is a draft.

## Data sources

Every source is free. Nothing in this project requires a paid tier, a subscription, or a funded account.

- Company annual reports and quarterly filings - the same company as the reverse DCF, reusing its cited source list

## How to run

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

# Day 1: ingest a ticker's historical financials into the normalized schema
# (model/historical.py) and report per-year margins, net debt and the
# realized revenue CAGR. Offline by default - reads the committed
# data/<ticker>/financials.csv.
python -m model.ingest --ticker GULFOILLUB

# Day 2: driver-based revenue build (model/revenue_driver.py) - domestic vs.
# export revenue reconciled against the Day 1 fixture, each segment's own
# historical CAGR, and a forward forecast using each segment's own growth
# rate (overridable per segment).
python -m model.revenue --ticker GULFOILLUB
python -m model.revenue --ticker GULFOILLUB --forecast-years 3 --domestic-growth 0.10 --export-growth 0.15

# Day 3: cost structure, D&A, capex and working-capital schedules
# (model/schedules.py) - each expressed as a margin of revenue, defaulting to
# a trailing historical average (overridable), chained onto Day 2's revenue
# forecast rather than re-deriving one.
python -m model.costs --ticker GULFOILLUB
python -m model.costs --ticker GULFOILLUB --forecast-years 3 --ebitda-margin 0.15 --capex-margin 0.02

# Day 4: debt schedule (model/debt_schedule.py) - mandatory amortization,
# revolver draw/cash-sweep, and interest on the average debt balance behind
# an explicit circularity toggle. Chains onto Day 3's EBITDA/capex/working-
# capital forecast for a pre-tax, pre-interest cash-available-for-debt-
# service (CFADS) proxy.
python -m model.debt --ticker GULFOILLUB
python -m model.debt --ticker GULFOILLUB --forecast-years 3 --no-circular
python -m model.debt --ticker GULFOILLUB --amort-rate 0.05 --revolver-limit 40000 --interest-rate 0.07

python -m model.build --ticker EXAMPLE.NS --years 5 --export outputs/model.xlsx
```

Runs offline against committed fixtures by default. Live data needs a key in `.env` (see `.env.example`); the fixture path is the default so nothing blocks on network access.

## Findings

**Day 1 - historical statement ingestion.** `data/GULFOILLUB/financials.csv` is reused verbatim from reverse-dcf-engine's own Day 2 transcription, per `NEXT_STEPS.md`'s own instruction to reuse project 2's company and cited sources rather than re-sourcing ten years of annual reports a second time (see `research/sources.md` for exactly what was and wasn't re-derived, and where the real page citations live). `model/historical.py` turns that flat, 14-column CSV into three typed objects per fiscal year (`IncomeStatement`, `BalanceSheetSummary`, `CashFlowSummary`) and checks two identities the source data implies by construction - `ebitda - depreciation_amortization == ebit` and `ebit - interest_expense - tax_expense == net_profit` - both pass cleanly on all 10 years, confirming the copy is byte-for-byte faithful to the source rather than corrupted in transit.

`python -m model.ingest --ticker GULFOILLUB` reports FY2014-15 through FY2023-24: EBIT margin ranges 11.68%-18.87%, net margin 7.75%-12.32%, and net debt swings from +₹6,333 lakh (FY2014-15, debt exceeds cash) to -₹37,293 lakh (FY2023-24, cash exceeds debt by a wide margin - a company that has been building a large net cash position, not drawing one down). Realized revenue CAGR over the 9-year span is **+14.54%**, matching reverse-dcf-engine's own figure for the same company and window exactly - a real cross-check that the copied data and the independently-written CAGR calculation here agree, not just a restated number.

**What this schema deliberately does not have, and why it matters for later days.** `BalanceSheetSummary` carries only `total_assets`, `total_debt`, `cash_and_equivalents` and `net_working_capital` - no `total_equity` field, because the source CSV has no liabilities/equity breakdown to derive one from honestly. `CashFlowSummary` carries only `capex` and the non-cash D&A add-back - no financing or working-capital-movement lines. Day 5's balance-check assertion (`assets = liabilities + equity`) cannot be built on this schema alone; it will need either a second transcription pass against the actual annual reports for the missing granularity, or an explicit, documented decision about what a plug here would mean (see `research/sources.md`). Flagged now rather than discovered as a Day 5 blocker.

20/20 tests pass (`tests/test_historical.py`): CSV structure/duplicate-year/non-numeric rejection, both identity checks against synthetic broken rows and the real fixture, the normalized dataclasses' derived properties (EBIT margin, net margin, net debt), and the CLI's success, missing-file, and identity-failure paths, all run against the real committed fixture as well as synthetic cases. `python -m model.ingest --ticker GULFOILLUB` and `--ticker NOPE` (the missing-data path) were both run by hand.

**Day 2 - driver-based revenue build.** Checked what Gulf Oil Lubricants India actually discloses before picking a driver, rather than assuming the "units x price" shape `NEXT_STEPS.md` suggests for a lubricants company. Searched all ten annual reports' text: no absolute sales volume (KL/litres/MT) is disclosed anywhere, only qualitative commentary ("volume growth 2-3x industry"), and the Ind AS 108 segment note states the Company has one reportable segment, "Lubricants" - there is no automotive/industrial or B2B/B2C revenue split in the audited statements either. A true units x price build cannot be done honestly here without inventing a volume base number, which this repo will not do - exactly the trap `NEXT_STEPS.md` names ("segment disclosure in Indian filings is often coarser than the driver build wants").

What every annual report *does* disclose, every year, is a mandatory geographic revenue split (India vs. Outside India). `model/revenue_driver.py` uses that as the real driver: `data/GULFOILLUB/segment_revenue.csv` sources `export_revenue` directly from each year's Note 37/38 (cited with PDF page numbers in `research/sources.md`), and domestic revenue is derived as `financials.csv`'s total revenue minus export revenue - not stored as a second number that could drift out of sync. Domestic and export revenue are then each modeled on their own historical CAGR (domestic +13.93%, export +34.21%, FY2014-15 to FY2023-24) and forecast forward independently, rather than one blended top-line growth percentage typed into a single cell. Export has grown from 1.47% of revenue in FY2014-15 to 6.14% by FY2023-24 - a real, structurally distinct trend this split actually captures that a single growth rate would average away.

26/26 new tests pass (`tests/test_revenue_driver.py`, 46/46 total): fiscal-year label arithmetic, CSV structure/duplicate rejection, the domestic+export-equals-total reconciliation against the real fixture (the core correctness check - every one of the 10 years sums exactly, and FY2016-17/FY2017-18's derived domestic figure independently reproduces the segment note's own reported "India" line to the rupee despite that note's total being gross of excise duty those two years), fiscal-year-mismatch and out-of-range sanity checks, segment CAGR and forecast math against hand-computed values, and the CLI's success, override, and three error paths (missing financials file, missing segment file, reconciliation failure), all run against the real committed fixtures. `python -m model.revenue --ticker GULFOILLUB` (default and with `--forecast-years`/growth overrides) and the `--ticker NOPE` missing-data path were both run by hand.

**Day 3 - cost structure, D&A, capex and working-capital schedules.** The data has no cost-by-nature breakdown (no cost of materials consumed, employee benefit expense, or other expenses line) and no PP&E gross block, so the cost structure uses the only honest aggregate available: EBITDA margin, not a bottom-up build - the same kind of disclosure gap Day 2 hit for segment volumes, handled the same way (pick the real driver the filings support, don't invent the one they don't). `model/schedules.py` expresses all four Day 3 schedules as margins of revenue, built straight off the already-ingested `HistoricalStatement`s. D&A is driven by revenue, not capex: checked by hand before picking the driver, D&A/capex swings 13%-394% across the ten historical years because D&A depreciates an accumulating gross block this data doesn't carry, while D&A/revenue drifts smoothly 0.50% -> 2.05% over the same span. Capex/revenue is genuinely lumpy (0.52%-8.10%, driven by discrete capacity expansions, e.g. FY2017-18's 8.10%) and NWC/revenue ranges 8.11%-23.66% with a level shift after FY2016-17 - both left lumpy rather than smoothed into a trend that isn't really there. Every margin defaults to a 3-year trailing average (overridable individually via `--ebitda-margin`/`--da-margin`/`--capex-margin`/`--nwc-margin`), picked over a single last year because capex especially is too noisy for one year to be a representative assumption. `model/costs.py`'s forecast chains directly onto Day 2's `forecast_revenue` output rather than re-deriving a revenue number, and also reports `delta_nwc`, the year-over-year change in working capital Day 5's cash-flow statement will need.

19/19 new tests pass (`tests/test_schedules.py`, 65/65 total): the historical schedule against hand-computed margins for the real fixture, the trailing-average helper's edge cases, forecast math against both default-margin and explicit-override cases, `delta_nwc` chaining across two forecast years, the Day 2 -> Day 3 revenue-forecast integration, and the CLI's success, zero-forecast, two missing-file, and override paths. `python -m model.costs --ticker GULFOILLUB` (default, with `--forecast-years 0`, and with all four margin overrides) and the `--ticker NOPE` missing-data path were all run by hand.

**Day 4 - debt schedule.** The source data has no split between term debt and a revolving facility, no disclosed amortization schedule, and no stated interest rate or revolver facility size - three separate gaps, each handled honestly rather than papered over with one invented number. `model/debt_schedule.py` treats historical `total_debt` as the opening term-debt balance and amortizes it at a flat, explicitly-labeled-as-an-assumption rate (`DEFAULT_AMORTIZATION_RATE = 10%`/year of the opening balance, overridable via `--amort-rate`); the revolver limit defaults to the historical peak `total_debt` (`default_revolver_limit`, overridable via `--revolver-limit`) since no facility size is disclosed either. The interest rate is the one piece that *is* derivable rather than invented: `interest_expense / average(total_debt)` gives a real implied effective rate for 9 of the 10 historical years (3.47%-10.93%, no clean trend), and the default interest rate is the trailing 3-year average of those implied rates (7.38%), the same override-the-driver pattern Day 3 used for margins.

The circularity this schedule has to resolve: interest on the *average* of opening and closing debt is standard (it does not overstate interest in a paydown year) but the closing balance depends on how much cash is left to pay the revolver down, which depends on interest expense, which depends on the closing balance. `--circular`/`--no-circular` makes the resolution a visible choice rather than an implementation detail: the default (`circular=True`) fixed-point-iterates interest against the average balance until it stops moving (bounded by `max_iterations`, and `converged=False` is reported rather than silently accepted if it doesn't); `--no-circular` charges interest on the opening balance only, a one-pass approximation that trades accuracy for not iterating. On the real fixture the two modes produce visibly different interest figures in every paydown year (e.g. FY2024-25: ₹2,309.75 circular vs. ₹2,431.31 non-circular) - a real, checkable difference, not a cosmetic flag.

Honest result on this company's real numbers: CFADS (the pre-tax, pre-interest proxy `EBITDA - capex - delta_nwc` the CLI derives from Day 3's own forecast) comfortably covers scheduled amortization and interest in every one of the 3 forecast years, so the revolver never draws and the `unmet_financing_gap` the schedule is built to report honestly if the facility limit is ever too small stays at zero throughout - the stress case is exercised only by the synthetic tests, not by this company's own fixture. That CFADS proxy is a deliberate, documented simplification: it excludes cash taxes, because cash tax depends on pretax income, which is EBIT minus *this schedule's own* interest output - taxing the proxy here would just relocate the circularity Day 5's full linkage has to resolve (income statement -> cash taxes -> debt schedule -> interest -> income statement) rather than resolve it, so it is left out and flagged rather than faked with an approximate tax figure.

27/27 new tests pass (`tests/test_debt_schedule.py`, 92/92 total): the historical implied-rate calculation against hand-computed values for the real fixture, the default interest-rate/revolver-limit derivations, amortization math (flat rate, floor at zero, default vs. override), the non-circular opening-balance interest calculation, the circular average-balance interest calculation (checked against its own definition: converged interest must equal rate times the average of opening and ending total debt) and that the two modes produce different numbers in a paydown year, revolver draw/repay/cash-sweep behavior under synthetic shortfall and surplus scenarios, the `unmet_financing_gap` path when a revolver limit is deliberately set too small to cover a shortfall, the real Day 3 -> Day 4 CFADS integration, and the CLI's success, zero-forecast-years, two missing-file, and override paths. `python -m model.debt --ticker GULFOILLUB` (default circular mode, `--no-circular`, and with all three parameter overrides) and the `--ticker NOPE` missing-data path were all run by hand.

## Checkpoint log

<!-- CHECKPOINTS:START -->
| Date | Commit | What changed | Next |
|------|--------|--------------|------|
| 2026-10-11 | `4261f07` | Day 3: cost structure, D&A, capex and working-capital schedules (model/schedules.py). The data has no cost-by-nature breakdown and no PP&E gross block, so cost structure uses EBITDA margin (the real aggregate the filings support) and D&A is driven by revenue rather than capex - D&A/capex swings 13%-394% across the ten historical years with no accumulating gross block to anchor it, while D&A/revenue drifts smoothly 0.50% to 2.05%, checked by hand before picking the driver. Capex/revenue (0.52%-8.10%, lumpy capacity expansions) and NWC/revenue (8.11%-23.66%, level shift after FY2016-17) are both left lumpy rather than smoothed into a trend that is not really there. Every margin defaults to a 3-year trailing average, individually overridable via model/costs.py's --ebitda-margin/--da-margin/--capex-margin/--nwc-margin flags, and the forecast chains directly onto Day 2's forecast_revenue output instead of re-deriving revenue. 19 new tests pass (tests/test_schedules.py, 65/65 total): historical margins against hand-computed values, the trailing-average helper's edge cases, forecast math for default and overridden margins, delta_nwc chaining across forecast years, the Day2->Day3 integration, and the CLI's success/zero-forecast/missing-file/override paths. python -m model.costs --ticker GULFOILLUB was run by hand in every mode, including the --ticker NOPE missing-data path. | Day 4 - debt schedule: mandatory amortization, revolver, cash sweep, interest on average debt with an explicit circularity toggle |
| 2026-10-11 | `dd8767b` | Day 2: driver-based revenue build (model/revenue_driver.py), domestic vs. export segments. Gulf Oil Lubricants India discloses no absolute sales volume in any annual report (only qualitative volume-growth commentary) and reports a single Ind AS 108 'Lubricants' segment with no automotive/industrial split, so a units x price build isn't buildable honestly - the exact trap NEXT_STEPS.md names. Used the one driver every filing does disclose: the mandatory geographic revenue split (India / Outside India), sourced directly from each year's Note 37/38 (research/sources.md cites every figure with a PDF page number). Domestic revenue is derived as financials.csv's total minus sourced export revenue, never stored as a second number that could drift; each segment is modeled on its own historical CAGR (domestic +13.93%, export +34.21%, FY2014-15 to FY2023-24, export now 6.14% of revenue vs 1.47% in FY2014-15) and forecast forward independently via model/revenue.py, with growth-rate overrides since naively compounding export's CAGR forever is implausible (flagged in Limitations). 26 new tests pass (tests/test_revenue_driver.py, 46/46 total): the domestic+export-equals-total reconciliation against the real fixture, sanity checks, CAGR/forecast math, and the CLI's success and three error paths. python -m model.revenue --ticker GULFOILLUB (default and with --forecast-years/growth overrides) and the --ticker NOPE path were both run by hand. | Day 3 - cost structure, D&A schedule, capex, working capital schedules |
| 2026-10-11 | `d4678df` | Day 1: historical statement ingestion into a normalized schema (model/historical.py). Reused reverse-dcf-engine's own Day 2 transcription of Gulf Oil Lubricants India's ten-year financials (data/GULFOILLUB/financials.csv) rather than re-sourcing the same filings a second time, per NEXT_STEPS.md's own instruction (research/sources.md records exactly what was reused and where the real page citations live). Turns the flat 14-column CSV into typed IncomeStatement/BalanceSheetSummary/CashFlowSummary objects per fiscal year and checks two identities the source data implies by construction (ebitda - D&A == ebit; ebit - interest - tax == net_profit), both passing cleanly on all 10 years. The balance-sheet/cash-flow schemas are deliberately thin -- no total_equity field, no financing/working-capital cash-flow lines -- because the source data has no liabilities/equity breakdown to derive them from honestly; flagged in Limitations as a gap Day 5's balance-check will need a second transcription pass to close, not a plug. python -m model.ingest --ticker GULFOILLUB reports realized revenue CAGR +14.54% (FY2014-15 to FY2023-24), matching reverse-dcf-engine's own figure for the same company exactly. 20/20 tests pass (tests/test_historical.py); the CLI was run by hand against the real fixture and the missing-file error path. | Day 2 - driver-based revenue build (units x price, or segment volumes, or stores x revenue per store), not a growth percentage typed into a cell |
<!-- CHECKPOINTS:END -->

## Limitations and what would make me wrong

- A forecast is a set of assumptions, not a prediction. The sensitivity tables show which two assumptions actually move the answer.
- Segment disclosure in Indian filings is often coarser than the driver build wants, so some drivers are estimated and flagged. Concretely for Gulf Oil Lubricants India: no annual report discloses an absolute sales volume figure (KL/litres/MT), only qualitative volume-growth commentary, and the Ind AS 108 segment note reports a single "Lubricants" segment with no automotive/industrial or B2B/B2C revenue split. `model/revenue_driver.py`'s domestic-vs-export driver is the real substitute - the one quantitative, decomposable split the filings actually give every year - not a units x price build.
- The domestic/export split's historical CAGRs (`model.revenue_driver.segment_cagr`) are extrapolations of a 9-year trend, most pronounced for export (+34.21% CAGR off a small base, now ~6% of revenue). Naively compounding that rate for many years would make exports an implausibly large share of revenue; `model/revenue.py --export-growth` exists precisely so a later day's full build can override it with a decelerating or capped assumption instead of trusting the historical CAGR forever.
- Corporate actions during the forecast window would change the share count; the equity roll-forward handles the disclosed ones only.
- `data/GULFOILLUB/financials.csv` is reused from reverse-dcf-engine's own transcription (see `research/sources.md`), not independently re-sourced. It carries no balance-sheet liabilities/equity breakdown and no full cash-flow statement - `model.historical.BalanceSheetSummary` and `CashFlowSummary` only expose the fields the source data actually has (`total_assets`/`total_debt`/`cash_and_equivalents`/`net_working_capital`, and `capex`/D&A respectively). Day 5's full linkage and balance-check assertion will need a second transcription pass for the missing granularity, or an explicit documented plug policy - neither exists yet.
- The two Day 1 identity checks (`ebitda - D&A == ebit`, `ebit - interest - tax == net_profit`) are tautologies by construction, since reverse-dcf-engine derived those columns that way from two reported numbers in the first place. Passing them confirms the copy wasn't corrupted; it is not independent evidence the ten years of hand-transcribed figures are correct against the original filings - that assurance is only as strong as reverse-dcf-engine's own citation ledger.
- `model/schedules.py`'s cost structure is EBITDA margin only - there is no cost-of-materials/employee-cost/other-expense breakdown in the source data to build a bottom-up cost structure from. D&A is modeled as a margin of revenue rather than of capex specifically because D&A/capex is not stable here (13%-394% across the ten historical years) without a PP&E gross block this data doesn't carry. Capex/revenue (0.52%-8.10%) and NWC/revenue (8.11%-23.66%, with a level shift after FY2016-17) are both genuinely lumpy, not smoothly trending; the default 3-year trailing average is a deliberate smoothing choice, not a claim that the lumpiness is noise - a future capacity expansion like FY2017-18's would push realized capex well above what `model/costs.py`'s trailing average projects.
- `model/debt_schedule.py` has to invent two things the filings never disclose: the source data gives one blended `total_debt` figure, not a term-debt/revolver split, an amortization schedule, or a revolver facility size. The 10%/year flat amortization rate and the historical-peak-`total_debt` revolver limit are both labeled assumptions, individually overridable, not facts read off a loan agreement - treat the resulting ending-debt path as illustrative, not as this company's actual repayment schedule. The interest rate is the one derived figure (`interest_expense / average(total_debt)`, trailing-averaged), which is real but still only an aggregate effective rate across whatever mix of facilities this company actually has, not a single bond's coupon.
- The revolver, cash-sweep, and `unmet_financing_gap` logic is exercised end to end only by `tests/test_debt_schedule.py`'s synthetic cases - on Gulf Oil Lubricants India's own real cash flow, CFADS (the Day 3-derived, pre-tax, pre-interest proxy `model/debt.py` computes) comfortably covers debt service in every forecast year, so the revolver never actually draws against the real fixture. The draw/repay/shortfall paths are correct by construction and by test, not yet by a real stressed example.
- The CFADS proxy `model/debt.py` feeds the debt schedule (`EBITDA - capex - delta_nwc`) deliberately excludes cash taxes. Taxing it properly needs pretax income, which is EBIT minus this same schedule's own interest output - computing it here would relocate, not resolve, the circularity Day 5's full linkage has to close (income statement -> cash taxes -> debt schedule -> interest expense -> income statement). Interest and debt balances in this day's output are therefore modestly overstated relative to what a tax-aware CFADS would produce, by the amount of the (unmodeled) interest tax shield on cash available for repayment.

## Where this sits

Part of a nine-repo research pipeline. Stock Stalker screens the NSE universe; this repo publishes a versioned artifact it reads back:

```json
{
  "fundamentals": {
    "fy3_revenue_cagr": 0.11,
    "fy3_ebit_margin": 0.19,
    "balance_check": "passed"
  }
}
```

Communication is by file contract, not imports, so either side can be refactored without breaking the other.

## Exam mapping

Series XV ch.8 (financial analysis), ch.8.13 (forecasting using ratio analysis), ch.9 (corporate actions)

---

CLI only, by design. No dashboard, no server. Charts and documents are written to `outputs/`.

# Three-statement model from primary filings

A fully linked income statement, balance sheet and cash flow forecast built from the filings with no template underneath, where the balance check is a test that fails loudly.

**Status:** Last checkpoint 2026-10-11 · Next: Day 2 - driver-based revenue build (units x price, or segment volumes, or stores x revenue per store), not a growth percentage typed into a cell

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

python -m model.build --ticker EXAMPLE.NS --years 5 --export outputs/model.xlsx
```

Runs offline against committed fixtures by default. Live data needs a key in `.env` (see `.env.example`); the fixture path is the default so nothing blocks on network access.

## Findings

**Day 1 - historical statement ingestion.** `data/GULFOILLUB/financials.csv` is reused verbatim from reverse-dcf-engine's own Day 2 transcription, per `NEXT_STEPS.md`'s own instruction to reuse project 2's company and cited sources rather than re-sourcing ten years of annual reports a second time (see `research/sources.md` for exactly what was and wasn't re-derived, and where the real page citations live). `model/historical.py` turns that flat, 14-column CSV into three typed objects per fiscal year (`IncomeStatement`, `BalanceSheetSummary`, `CashFlowSummary`) and checks two identities the source data implies by construction - `ebitda - depreciation_amortization == ebit` and `ebit - interest_expense - tax_expense == net_profit` - both pass cleanly on all 10 years, confirming the copy is byte-for-byte faithful to the source rather than corrupted in transit.

`python -m model.ingest --ticker GULFOILLUB` reports FY2014-15 through FY2023-24: EBIT margin ranges 11.68%-18.87%, net margin 7.75%-12.32%, and net debt swings from +₹6,333 lakh (FY2014-15, debt exceeds cash) to -₹37,293 lakh (FY2023-24, cash exceeds debt by a wide margin - a company that has been building a large net cash position, not drawing one down). Realized revenue CAGR over the 9-year span is **+14.54%**, matching reverse-dcf-engine's own figure for the same company and window exactly - a real cross-check that the copied data and the independently-written CAGR calculation here agree, not just a restated number.

**What this schema deliberately does not have, and why it matters for later days.** `BalanceSheetSummary` carries only `total_assets`, `total_debt`, `cash_and_equivalents` and `net_working_capital` - no `total_equity` field, because the source CSV has no liabilities/equity breakdown to derive one from honestly. `CashFlowSummary` carries only `capex` and the non-cash D&A add-back - no financing or working-capital-movement lines. Day 5's balance-check assertion (`assets = liabilities + equity`) cannot be built on this schema alone; it will need either a second transcription pass against the actual annual reports for the missing granularity, or an explicit, documented decision about what a plug here would mean (see `research/sources.md`). Flagged now rather than discovered as a Day 5 blocker.

20/20 tests pass (`tests/test_historical.py`): CSV structure/duplicate-year/non-numeric rejection, both identity checks against synthetic broken rows and the real fixture, the normalized dataclasses' derived properties (EBIT margin, net margin, net debt), and the CLI's success, missing-file, and identity-failure paths, all run against the real committed fixture as well as synthetic cases. `python -m model.ingest --ticker GULFOILLUB` and `--ticker NOPE` (the missing-data path) were both run by hand.

## Checkpoint log

<!-- CHECKPOINTS:START -->
| Date | Commit | What changed | Next |
|------|--------|--------------|------|
| 2026-10-11 | `d4678df` | Day 1: historical statement ingestion into a normalized schema (model/historical.py). Reused reverse-dcf-engine's own Day 2 transcription of Gulf Oil Lubricants India's ten-year financials (data/GULFOILLUB/financials.csv) rather than re-sourcing the same filings a second time, per NEXT_STEPS.md's own instruction (research/sources.md records exactly what was reused and where the real page citations live). Turns the flat 14-column CSV into typed IncomeStatement/BalanceSheetSummary/CashFlowSummary objects per fiscal year and checks two identities the source data implies by construction (ebitda - D&A == ebit; ebit - interest - tax == net_profit), both passing cleanly on all 10 years. The balance-sheet/cash-flow schemas are deliberately thin -- no total_equity field, no financing/working-capital cash-flow lines -- because the source data has no liabilities/equity breakdown to derive them from honestly; flagged in Limitations as a gap Day 5's balance-check will need a second transcription pass to close, not a plug. python -m model.ingest --ticker GULFOILLUB reports realized revenue CAGR +14.54% (FY2014-15 to FY2023-24), matching reverse-dcf-engine's own figure for the same company exactly. 20/20 tests pass (tests/test_historical.py); the CLI was run by hand against the real fixture and the missing-file error path. | Day 2 - driver-based revenue build (units x price, or segment volumes, or stores x revenue per store), not a growth percentage typed into a cell |
<!-- CHECKPOINTS:END -->

## Limitations and what would make me wrong

- A forecast is a set of assumptions, not a prediction. The sensitivity tables show which two assumptions actually move the answer.
- Segment disclosure in Indian filings is often coarser than the driver build wants, so some drivers are estimated and flagged.
- Corporate actions during the forecast window would change the share count; the equity roll-forward handles the disclosed ones only.
- `data/GULFOILLUB/financials.csv` is reused from reverse-dcf-engine's own transcription (see `research/sources.md`), not independently re-sourced. It carries no balance-sheet liabilities/equity breakdown and no full cash-flow statement - `model.historical.BalanceSheetSummary` and `CashFlowSummary` only expose the fields the source data actually has (`total_assets`/`total_debt`/`cash_and_equivalents`/`net_working_capital`, and `capex`/D&A respectively). Day 5's full linkage and balance-check assertion will need a second transcription pass for the missing granularity, or an explicit documented plug policy - neither exists yet.
- The two Day 1 identity checks (`ebitda - D&A == ebit`, `ebit - interest - tax == net_profit`) are tautologies by construction, since reverse-dcf-engine derived those columns that way from two reported numbers in the first place. Passing them confirms the copy wasn't corrupted; it is not independent evidence the ten years of hand-transcribed figures are correct against the original filings - that assurance is only as strong as reverse-dcf-engine's own citation ledger.

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

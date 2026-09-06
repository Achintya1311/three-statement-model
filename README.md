# Three-statement model from primary filings

A fully linked income statement, balance sheet and cash flow forecast built from the filings with no template underneath, where the balance check is a test that fails loudly.

**Status:** Not started · Next: Day 1 - historical statement ingestion into normalized schema

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
python -m model.build --ticker EXAMPLE.NS --years 5 --export outputs/model.xlsx
```

Runs offline against committed fixtures by default. Live data needs a key in `.env` (see `.env.example`); the fixture path is the default so nothing blocks on network access.

## Findings

Nothing yet. This section fills in as the work lands, including the results that do not flatter the method.

## Checkpoint log

<!-- CHECKPOINTS:START -->
| Date | Commit | What changed | Next |
|------|--------|--------------|------|
<!-- CHECKPOINTS:END -->

## Limitations and what would make me wrong

- A forecast is a set of assumptions, not a prediction. The sensitivity tables show which two assumptions actually move the answer.
- Segment disclosure in Indian filings is often coarser than the driver build wants, so some drivers are estimated and flagged.
- Corporate actions during the forecast window would change the share count; the equity roll-forward handles the disclosed ones only.

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

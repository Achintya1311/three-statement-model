# Sourcing note (Day 1)

`data/GULFOILLUB/financials.csv` in this repo is **not a fresh transcription**.
It is byte-for-byte the same file `reverse-dcf-engine` (project 2) produced on
Day 2 of that project, copied here per `NEXT_STEPS.md`'s own instruction to
reuse "the same company chosen in project 2, reusing `data/<TICKER>/` and its
cited sources" rather than re-sourcing or re-transcribing ten years of annual
reports a second time for the same company.

Every cell's citation (document and page, FY2014-15 through FY2023-24) lives
in `reverse-dcf-engine`'s own `research/sources.md` (a ~130-row ledger) and its
`README.md` Findings section, not duplicated here. If a figure in
`data/GULFOILLUB/financials.csv` is ever in doubt, that is where to check it.

## What this data actually is, and is not

The columns this file carries — `revenue`, `ebitda`,
`depreciation_amortization`, `ebit`, `interest_expense`, `tax_expense`,
`net_profit`, `total_assets`, `total_debt`, `cash_and_equivalents`,
`net_working_capital`, `capex`, `shares_outstanding` — are the condensed set
`reverse-dcf-engine` needed for a forward/reverse DCF, not a full three-way
statement extract. In particular:

- There is **no balance-sheet liabilities or equity breakdown** — only
  `total_assets` and `total_debt` (interest-bearing debt). `total_equity`
  cannot be derived from this file without inventing a number for every other
  liability (trade payables, provisions, deferred tax, etc.), which this repo
  will not do silently. `reverse-dcf-engine`'s own README notes it hit the
  same gap for its book-value capital structure calculation.
- There is **no full cash flow statement** — only `capex` and
  `depreciation_amortization` (a non-cash add-back), not the working-capital
  movement, financing activity, or dividend lines a complete CFS needs.

Day 5's full linkage and balance-check assertion will need a second
transcription pass against the source annual reports for the missing
balance-sheet and cash-flow granularity — flagged now, in Limitations, rather
than discovered as a blocker on Day 5.

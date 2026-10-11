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

## Day 2 — revenue driver sourcing (2026-10-11)

`NEXT_STEPS.md` Day 2 asks for a driver-based revenue build ("units × price,
or segment volumes, or stores × revenue per store"). Before picking a driver,
checked what Gulf Oil Lubricants India actually discloses, rather than
assuming the units × price shape a lubricants company suggests.

**No sales volume is disclosed, in any form stronger than qualitative
commentary.** Searched all ten annual reports' text (FY2014-15 through
FY2023-24) for an absolute sales volume in kilolitres, litres or metric
tonnes. Every hit on "KL" is manufacturing **capacity** (e.g. "annual
production capacity of 90,000 KL for lubricant", FY2023-24 AR) or an
unrelated ESG water-withdrawal figure, never units sold. Volume growth
itself appears only as qualitative, index-style commentary — "volume
growth 2-3 times the industry average", "robust double-digit volume
growth" — with no absolute base number given in any year. This is exactly
the trap `NEXT_STEPS.md` names: "segment disclosure in Indian filings is
often coarser than the driver build wants." A units × price build cannot
be done honestly here without inventing a volume base figure, which this
repo will not do.

**No product/business segment split either.** Note 37/38 ("Segment
Information") in every annual report checked (FY2014-15, FY2015-16,
FY2016-17, FY2017-18, FY2019-20, FY2020-21, FY2021-22, FY2023-24) states the
Company has integrated automotive and non-automotive operations into one
Ind AS 108 reportable segment, "Lubricants" — there is no Automotive vs.
Industrial or B2B vs. B2C revenue split in the audited financial statements
(that split appears only as unquantified narrative in the Management
Discussion & Analysis, e.g. "both B2C and B2B segments" grew — no rupee
figures attached).

**What *is* disclosed every year: a geographic revenue split.** The same
segment note always carries a secondary/geographic breakdown — "India" and
"Outside India" revenue — because Ind AS/AS-17 require it regardless of the
single-segment conclusion above. This is the one real, quantitative,
decomposable driver the filings actually give: domestic lubricants revenue
and export revenue are genuinely different businesses (export is a much
smaller, faster-growing share of the mix — about 1.5% of revenue in
FY2014-15, about 6.1% by FY2023-24), so modeling them on their own separate
trajectories is a real driver-based build, not a single blended top-line
growth percentage typed into one cell — it is the closest honest substitute
for "segment volumes" this company's own disclosures support.

`data/GULFOILLUB/segment_revenue.csv` carries one column sourced directly
from each annual report, `export_revenue` ("Outside India" revenue, ₹ Lakh).
Domestic revenue is **not** stored as a second sourced column; it is derived
in `model/revenue_driver.py` as `total_revenue (from financials.csv) −
export_revenue`, which is the quantity actually wanted for the three-statement
build and sidesteps a unit mismatch explained next.

**A unit wrinkle in two years, resolved by construction, not patched.**
`research/sources.md`'s own methodology for `financials.csv` (copied from
reverse-dcf-engine) nets excise duty out of `revenue` for FY2016-17 and
FY2017-18, the two pre-GST years whose P&L reported revenue gross of excise
duty with excise shown as a matching expense line. The segment note's own
"Total" for those two years is correspondingly gross of excise and does not
equal `financials.csv`'s net revenue for the same year (e.g. FY2016-17: note
total ₹113,105.67 Lakh vs. `financials.csv`'s ₹108,679.27 Lakh). Export sales
are not subject to India's domestic excise duty (the standard treatment,
and consistent with every Ind-AS year's reported "Outside India" figure
equalling the segment note's own gross-vs-net-reconciled total with no
excise adjustment needed), so the note's "Outside India" figure is used
as-is for every year including these two, and domestic revenue is always
derived as the residual against the *net* total from `financials.csv` —
which is why the two numbers are guaranteed to reconcile by construction
instead of by a second coincidental excise adjustment. Verified for every
other year that `financials.csv` revenue − `export_revenue` reproduces the
segment note's own reported "India" figure to the rupee (e.g. FY2019-20:
₹164,350.07 − ₹8,283.03 = ₹156,067.04, matching the note exactly) — a real
cross-check, not an assumption taken on faith.

## Citation ledger — export_revenue (segment_revenue.csv)

One row per fiscal year, all figures "Revenue — Outside India" from Note
37/38 "Segment Information" ((b) Segment Revenue / Information about
Secondary Geographical Segments) of the standalone financial statements.
Page numbers are PDF page numbers (1-indexed), same convention as the
ledger above.

| fiscal_year | export_revenue (₹ Lakh) | source document | PDF page |
|---|---|---|---|
| FY2014-15 | 1,427.01 | Annual Report 2014-15 | 89 |
| FY2015-16 | 1,142.64 | Annual Report 2015-16 | 109 |
| FY2016-17 | 2,278.62 | Annual Report 2016-17 | 113 |
| FY2017-18 | 4,230.23 | Annual Report 2017-18 | 121 |
| FY2018-19 | 9,054.49 | Annual Report 2019-20 (comparative column) | 144 |
| FY2019-20 | 8,283.03 | Annual Report 2019-20 | 144 |
| FY2020-21 | 9,333.65 | Annual Report 2021-22 (comparative column) | 172 |
| FY2021-22 | 12,988.38 | Annual Report 2021-22 | 172 |
| FY2022-23 | 18,193.02 | Annual Report 2023-24 (comparative column) | 217 |
| FY2023-24 | 20,161.22 | Annual Report 2023-24 | 217 |

Both annual reports fetched directly from Gulf Oil's own investor-relations
archive (`assets.gulfoilltd.com`), reachable today without the egress block
the first sourcing pass of this data hit back on 2026-09-10/11 (see above) —
re-checked before use rather than assumed. FY2018-19 and FY2020-21 are read
from the following year's comparative column rather than their own year's
annual report, since both figures agree with the other sourcing pass having
already flagged FY2018-19's own annual report as missing from Gulf Oil's
archive (see above); using the FY2019-20 and FY2021-22 reports' comparative
columns avoids that gap entirely.

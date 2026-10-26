"""D50: data/GULFOILLUB/financials.csv is a copy of reverse-dcf-engine's transcription.

The copy is pinned by hash here, and compared with the sibling checkout
when one exists (the same pattern STOCKSTALKER's fixture provenance test
uses), so a change on either side fails a test instead of drifting.
"""

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FINANCIALS = ROOT / "data" / "GULFOILLUB" / "financials.csv"
SIBLING = ROOT.parent / "reverse-dcf-engine" / "data" / "GULFOILLUB" / "financials.csv"
PINNED_SHA256 = "c24ce65998ae04951b1784ff600862fb2f0e9572c7b62a7ca1a7c46c205c0b42"
SOURCE_COMMIT = "7ce6c8b"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_financials_match_the_pinned_hash():
    assert _sha256(FINANCIALS) == PINNED_SHA256, (
        "financials.csv changed: re-copy it from reverse-dcf-engine and update PINNED_SHA256, "
        "SOURCE_COMMIT and research/sources.md together"
    )


def test_sources_note_records_the_commit_and_hash():
    note = (ROOT / "research" / "sources.md").read_text()
    assert SOURCE_COMMIT in note
    assert PINNED_SHA256 in note


def test_financials_match_reverse_dcf_engine_when_checked_out():
    if not SIBLING.is_file():
        pytest.skip("reverse-dcf-engine is not checked out next to this repo")
    assert FINANCIALS.read_bytes() == SIBLING.read_bytes(), (
        "reverse-dcf-engine's financials.csv has changed; re-copy it and update the pin"
    )


# -- Day 156 (D51, D52, P101): the provenance text says what was and was not checked --


def test_readme_does_not_call_the_segment_reconciliation_a_check():
    readme = (ROOT / "README.md").read_text()
    assert "the core correctness check" not in readme
    assert "domestic + export equals total by construction" in readme
    assert "India figures were checked by hand and are not committed" in readme


def test_readme_names_the_export_ledger_vintages():
    readme = (ROOT / "README.md").read_text()
    assert "comparative column of the following year's annual report" in readme


def test_sources_note_has_no_stale_lines():
    note = (ROOT / "research" / "sources.md").read_text()
    assert "will need a second\ntranscription pass" not in note
    assert "Both annual reports fetched" not in note
    assert "**Vintage (D52).**" in note


def test_readme_says_the_workbook_is_generated_not_committed():
    chart_line = next(line for line in (ROOT / "README.md").read_text().splitlines() if line.startswith("**Chart:**"))
    assert "not committed" in chart_line
    assert "python -m model.build" in chart_line

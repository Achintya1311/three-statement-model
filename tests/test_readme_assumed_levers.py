"""P150 (CRITIQUES.md): the README's Method line counts the assumed levers as the code sets them."""

from pathlib import Path

from model.debt_schedule import DEFAULT_AMORTIZATION_RATE
from model.linkage import DEFAULT_DIVIDEND_PAYOUT

README = (Path(__file__).resolve().parents[1] / "README.md").read_text()


def _method_line():
    return next(line for line in README.splitlines() if line.startswith("**Method:**"))


def test_method_line_names_both_assumed_levers():
    method = _method_line()
    assert "nine are real historical ratios" not in method
    assert "eight are real historical ratios" in method
    assert f"dividend payout ({DEFAULT_DIVIDEND_PAYOUT:.0%})" in method
    assert f"amortisation rate ({DEFAULT_AMORTIZATION_RATE:.0%})" in method

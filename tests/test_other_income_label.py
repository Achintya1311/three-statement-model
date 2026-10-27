"""P123 (CRITIQUES.md): EBIT is PBT + finance costs, so EBITDA carries other income."""

from pathlib import Path

from model import sensitivity
from model.sensitivity import LABELS

README = (Path(__file__).resolve().parents[1] / "README.md").read_text()


def test_ebitda_margin_label_names_other_income():
    assert LABELS["ebitda_margin"] == "EBITDA margin (incl. other income)"


def test_ranking_table_prints_the_label_in_full(capsys):
    assert sensitivity.main(["--ticker", "GULFOILLUB"]) == 0
    assert "EBITDA margin (incl. other income)" in capsys.readouterr().out


def test_readme_limitations_say_ebitda_includes_other_income():
    limitations = README.split("## Limitations and what would make me wrong", 1)[1].split("\n## ", 1)[0]
    assert "other income" in limitations
    assert "P123" in limitations

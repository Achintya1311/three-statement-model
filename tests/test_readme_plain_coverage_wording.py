"""S30 (CRITIQUES.md): the README states the coverage result without grading the company."""

import re
from pathlib import Path

README = (Path(__file__).resolve().parents[1] / "README.md").read_text()


def test_readme_has_no_evaluative_coverage_words():
    assert not re.search(r"\bhealthy\b", README, re.IGNORECASE)
    assert not re.search(r"\bcomfortably\b", README, re.IGNORECASE)

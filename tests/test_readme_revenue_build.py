"""P124 (CRITIQUES.md): the README must describe the revenue build as the code does it."""

from pathlib import Path

README = (Path(__file__).resolve().parents[1] / "README.md").read_text()


def _what_this_is():
    return README.split("## What this is", 1)[1].split("\n## ", 1)[0]


def test_no_operating_driver_overclaim():
    assert "built from operating drivers rather than a growth percentage" not in README


def test_what_this_is_names_the_two_segment_growth_build():
    section = _what_this_is()
    assert "domestic and export" in section
    assert "no sales volumes" in section

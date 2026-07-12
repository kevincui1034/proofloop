"""Tagging vN with __version__ still at vN-1 ships a CLI that reports the
wrong version forever — this test turns drift into a CI failure."""

import tomllib
from pathlib import Path

import proofjury


def test_version_matches_pyproject():
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    assert proofjury.__version__ == data["project"]["version"]

"""Pytest configuration for file_extractor tests.

Adds the file_extractor/ directory to sys.path so tests can import
the top-level `extract` module and the `extractors` package, regardless
of where pytest is invoked from.

Also provides a `sample_pdf` fixture that locates a known ACP case-summary
PDF, searching candidate locations in order.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `extract` and `extractors` importable when pytest is run from
# the workspace root.
FILE_EXTRACTOR_ROOT = Path(__file__).resolve().parent.parent
if str(FILE_EXTRACTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(FILE_EXTRACTOR_ROOT))


SAMPLE_FILENAME = "Mint Health + Drugs Beaverlodge 3538 Report 1.pdf"

# Candidate locations searched in order. First hit wins.
SAMPLE_CANDIDATES = [
    FILE_EXTRACTOR_ROOT / "samples" / SAMPLE_FILENAME,
    Path("/Users/marklu/Desktop/db_holiday") / SAMPLE_FILENAME,
    Path("/Users/marklu/Desktop/Algo-Pharm_formal/raw_data/Mint_Action_Reports") / SAMPLE_FILENAME,
]


@pytest.fixture(scope="session")
def sample_pdf() -> Path:
    """Return a path to the Beaverlodge sample PDF, or skip if unavailable."""
    for candidate in SAMPLE_CANDIDATES:
        if candidate.exists():
            return candidate
    pytest.skip(
        f"Sample PDF not found. Checked: {[str(p) for p in SAMPLE_CANDIDATES]}"
    )

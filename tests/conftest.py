from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_DIFFS_DIR = FIXTURES_DIR / "sample_diffs"
SIMPLE_PYTHON_PROJECT = FIXTURES_DIR / "simple_python_project"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_diffs_dir() -> Path:
    return SAMPLE_DIFFS_DIR


@pytest.fixture
def simple_python_project() -> Path:
    return SIMPLE_PYTHON_PROJECT

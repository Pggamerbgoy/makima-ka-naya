"""
tests/conftest.py — pytest configuration for Makima v2 test suite.
Adds project root to sys.path so all verify_*.py and test_*.py files
can import makima.* without manual path manipulation.
"""
import sys
from pathlib import Path

# Insert project root (parent of tests/) into sys.path
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest
from makima.tools.filesystem.safe_io import set_workspace_dir


@pytest.fixture
def tmp_dir(tmp_path: Path):
    """Provides a temporary directory and sets it as the workspace dir during test."""
    set_workspace_dir(tmp_path)
    try:
        yield tmp_path
    finally:
        set_workspace_dir(None)

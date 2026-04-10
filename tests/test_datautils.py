"""
Tests for the datautils package.
"""

import pytest
from datautils import __version__


def test_version():
    """Test that the version is set correctly."""
    assert __version__ == "0.1.0"


def test_package_import():
    """Test that the package can be imported."""
    assert __version__ is not None

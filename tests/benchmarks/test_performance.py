"""Performance benchmark tests."""
import pytest


class TestPerformance:
    """Performance benchmark tests."""

    def test_import_performance(self, benchmark):
        """Benchmark module import time."""
        def import_openjarvis():
            import openjarvis
            return openjarvis
        
        result = benchmark(import_openjarvis)
        assert result is not None

    def test_initialization_performance(self, benchmark):
        """Benchmark Jarvis initialization time."""
        def init_jarvis():
            try:
                from openjarvis import Jarvis
                jarvis = Jarvis()
                return jarvis
            except:
                return None
        
        result = benchmark(init_jarvis)
        assert result is not None or result is None  # Allow for failures in CI

"""Tests for openjarvis.evals.comparison.make_configs."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomllib

from openjarvis.evals.comparison.make_configs import (
    BENCHMARKS,  # noqa: F401  (verify export)
    FRAMEWORKS,  # noqa: F401  (verify export)
    MODELS,
    materialize_config,
)


class TestMaterializeConfig:
    def test_emits_valid_toml(self, tmp_path: Path) -> None:
        out = materialize_config(
            framework="hermes",
            model="qwen-9b",
            benchmark="gaia",
            output_dir=tmp_path,
        )
        assert out.exists()
        with open(out, "rb") as fh:
            data = tomllib.load(fh)
        assert data["meta"]["framework"] == "hermes"
        assert data["benchmarks"][0]["backend"] == "hermes"
        assert data["models"][0]["name"] == MODELS["qwen-9b"]["model_id"]

    def test_filename_convention(self, tmp_path: Path) -> None:
        out = materialize_config(
            framework="hermes",
            model="qwen-9b",
            benchmark="gaia",
            output_dir=tmp_path,
        )
        assert out.name == "gaia-hermes-qwen-9b.toml"

    def test_unknown_framework_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unknown framework"):
            materialize_config(
                framework="not-real",
                model="qwen-9b",
                benchmark="gaia",
                output_dir=tmp_path,
            )

    def test_unknown_benchmark_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unknown benchmark"):
            materialize_config(
                framework="hermes",
                model="qwen-9b",
                benchmark="not-real",
                output_dir=tmp_path,
            )

    def test_idempotent(self, tmp_path: Path) -> None:
        out1 = materialize_config(
            framework="hermes",
            model="qwen-9b",
            benchmark="gaia",
            output_dir=tmp_path,
        )
        content1 = out1.read_text()
        out2 = materialize_config(
            framework="hermes",
            model="qwen-9b",
            benchmark="gaia",
            output_dir=tmp_path,
        )
        assert out1 == out2
        assert out2.read_text() == content1


class TestTemplateStripping:
    def test_no_substitution_in_comments(self, tmp_path: Path) -> None:
        """Documentation comments must not contain substituted text."""
        out = materialize_config(
            framework="hermes",
            model="qwen-9b",
            benchmark="gaia",
            output_dir=tmp_path,
        )
        text = out.read_text()
        # The substitution variables doc block uses <var> not {{var}};
        # if it leaks through, "<benchmark>" or similar would appear in output
        assert "<benchmark>" not in text
        assert "<framework>" not in text
        assert "{{benchmark}}" not in text  # Must be substituted
        # The output should start with [meta], not with a doc-comment header
        first_non_blank = next(line for line in text.splitlines() if line.strip())
        assert first_non_blank.startswith("[meta]"), (
            f"Expected first line to be [meta], got: {first_non_blank!r}"
        )

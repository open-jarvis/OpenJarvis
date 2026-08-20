.PHONY: setup build test lint format

# Mirrors .github/workflows/ci.yml so `make test` matches CI locally.

setup:
	uv sync --extra dev --extra framework-comparison --extra server

build:
	uv run maturin develop --manifest-path rust/crates/openjarvis-python/Cargo.toml

test: build
	uv run pytest tests/ -n auto -q --tb=short -m "not live and not cloud and not hub"

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

format:
	uv run ruff format src/ tests/

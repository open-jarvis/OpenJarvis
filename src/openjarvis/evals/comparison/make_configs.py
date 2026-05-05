"""CLI for generating framework-comparison eval configs from `_template.toml`.

Usage:
    python -m openjarvis.evals.comparison.make_configs \\
        --framework hermes --model qwen-9b --benchmark gaia
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import click

# ---------------------------------------------------------------------------
# Domain catalogs - single source of truth for what's a valid combo.
# Extend these dicts to add new frameworks / models / benchmarks.
# ---------------------------------------------------------------------------

FRAMEWORKS: Dict[str, Dict[str, str]] = {
    "openjarvis": {"backend_id": "jarvis-agent"},
    "openjarvis-distilled": {"backend_id": "jarvis-agent"},
    "hermes": {"backend_id": "hermes"},
    "openclaw": {"backend_id": "openclaw"},
}

MODELS: Dict[str, Dict[str, object]] = {
    "claude-opus-46": {
        "model_id": "claude-opus-4-6",
        "model_pretty": "Claude Opus 4.6",
        "engine": "cloud",
        "num_gpus": 0,
        "max_tokens": 8192,
    },
    "qwen-9b": {
        "model_id": "Qwen/Qwen3.5-9B",
        "model_pretty": "Qwen3.5-9B",
        "engine": "vllm",
        "num_gpus": 1,
        "max_tokens": 8192,
    },
    "qwen-122b": {
        "model_id": "Qwen/Qwen3.5-122B",
        "model_pretty": "Qwen3.5-122B",
        "engine": "vllm",
        "num_gpus": 4,
        "max_tokens": 8192,
    },
}

BENCHMARKS: Dict[str, Dict[str, object]] = {
    "toolcall15": {
        "max_samples": 15,
        "tools": ["think", "calculator"],
        "temperature": 0.0,
    },
    "pinchbench": {
        "max_samples": 23,
        "tools": ["think", "code_interpreter", "web_search", "file_read"],
        "temperature": 0.6,
    },
    "livecodebench": {
        "max_samples": 100,
        "tools": ["think", "code_interpreter"],
        "temperature": 0.2,
    },
    "taubench": {
        "max_samples": 100,
        "tools": ["think"],
        "temperature": 0.0,
    },
    "taubench-telecom": {
        "max_samples": 40,
        "tools": ["think"],
        "temperature": 0.0,
    },
    "gaia": {
        "max_samples": 50,
        "tools": [
            "think",
            "calculator",
            "code_interpreter",
            "web_search",
            "file_read",
        ],
        "temperature": 0.6,
    },
    "liveresearchbench": {
        "max_samples": 50,
        "tools": ["think", "web_search"],
        "temperature": 0.6,
    },
    "deepresearchbench": {
        "max_samples": 80,
        "tools": ["think", "web_search"],
        "temperature": 0.6,
    },
}

DEFAULT_JUDGE_MODEL = "gpt-5-mini-2025-08-07"


def _template_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "framework_comparison"
        / "_template.toml"
    )


def _default_output_dir() -> Path:
    return _template_path().parent


def materialize_config(
    framework: str,
    model: str,
    benchmark: str,
    output_dir: Optional[Path] = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
) -> Path:
    """Materialize one TOML config from the template."""
    if framework not in FRAMEWORKS:
        raise ValueError(f"unknown framework {framework!r}; valid: {list(FRAMEWORKS)}")
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}; valid: {list(MODELS)}")
    if benchmark not in BENCHMARKS:
        raise ValueError(f"unknown benchmark {benchmark!r}; valid: {list(BENCHMARKS)}")

    fwk = FRAMEWORKS[framework]
    mdl = MODELS[model]
    bnk = BENCHMARKS[benchmark]

    template = _template_path().read_text()
    sentinel = "# --- TEMPLATE BEGIN ---\n"
    if sentinel in template:
        template = template.split(sentinel, 1)[1]
    rendered = (
        template.replace("{{benchmark}}", benchmark)
        .replace("{{framework}}", framework)
        .replace("{{framework_id}}", fwk["backend_id"])
        .replace("{{model_pretty}}", str(mdl["model_pretty"]))
        .replace("{{model_id}}", str(mdl["model_id"]))
        .replace("{{model_slug}}", model)
        .replace("{{engine}}", str(mdl["engine"]))
        .replace("{{num_gpus}}", str(mdl["num_gpus"]))
        .replace("{{tools}}", json.dumps(bnk["tools"]))
        .replace("{{max_samples}}", str(bnk["max_samples"]))
        .replace("{{temperature}}", str(bnk["temperature"]))
        .replace("{{max_tokens}}", str(mdl["max_tokens"]))
        .replace("{{judge_model}}", judge_model)
    )

    out_dir = output_dir if output_dir is not None else _default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{benchmark}-{framework}-{model}.toml"
    out_path = out_dir / filename
    out_path.write_text(rendered)
    return out_path


@click.command()
@click.option("--framework", type=click.Choice(list(FRAMEWORKS)))
@click.option("--model", type=click.Choice(list(MODELS)))
@click.option("--benchmark", type=click.Choice(list(BENCHMARKS)))
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
)
@click.option(
    "--all-tier1",
    is_flag=True,
    help="Materialize the full configs grid (4 frameworks x 8 benchmarks x 3 models)",
)
def main(
    framework: Optional[str],
    model: Optional[str],
    benchmark: Optional[str],
    output_dir: Optional[Path],
    all_tier1: bool,
) -> None:
    """Generate eval config TOMLs for the framework-comparison experiment."""
    if all_tier1:
        tier1_models = ["claude-opus-46", "qwen-9b", "qwen-122b"]
        count = 0
        for f in FRAMEWORKS:
            for m in tier1_models:
                for b in BENCHMARKS:
                    p = materialize_config(f, m, b, output_dir)
                    click.echo(f"  wrote {p.name}")
                    count += 1
        click.echo(f"\nWrote {count} configs.")
        return

    if not framework or not model or not benchmark:
        raise click.UsageError(
            "Specify --framework + --model + --benchmark, or pass --all-tier1"
        )
    p = materialize_config(framework, model, benchmark, output_dir)
    click.echo(f"wrote {p}")


if __name__ == "__main__":
    main()

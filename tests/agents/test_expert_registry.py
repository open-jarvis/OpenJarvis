"""Tests for the faithful ToolOrchestra unified-tool registry."""

from __future__ import annotations

import random

import pytest

from openjarvis.agents.hybrid.expert_registry import (
    CATEGORY_BASIC,
    CATEGORY_CLOUD_FRONTIER,
    CATEGORY_LOCAL_OSS,
    ExpertTool,
    KIND_MODEL,
    KIND_TOOL,
    build_tool_specs,
    default_catalog,
    openjarvis_tool,
    orchestrator_catalog,
    sample_tool_config,
    to_worker_dict,
    tools_by_name,
)


def test_each_model_is_its_own_tool():
    """Faithful §3.1: one named tool per model, not a meta-tool + slot."""
    cat = default_catalog()
    names = {t.name for t in cat}
    # Distinct model tools, each with its own name.
    for n in ("gpt_5", "gpt_5_mini", "qwen3_32b", "qwen_2_5_coder_32b_instruct",
              "llama_3_3_70b_instruct", "claude_opus_4_7"):
        assert n in names, f"missing model tool {n}"
    # No meta-tool / slot vocabulary leaks in.
    assert "answer" not in names and "enhance_reasoning" not in names


def test_catalog_names_unique_and_valid():
    cat = default_catalog()
    names = [t.name for t in cat]
    assert len(names) == len(set(names))
    assert all(isinstance(t, ExpertTool) for t in cat)


def test_local_model_included_only_when_served():
    # Local tool is named after the served model ("qwen3:8b" -> "qwen3_8b").
    assert "qwen3_8b" not in {t.name for t in default_catalog()}
    cat = default_catalog(local_model="qwen3:8b", local_endpoint="http://x/v1")
    local = tools_by_name(cat)["qwen3_8b"]
    assert local.backend_type == "vllm"
    assert local.base_url == "http://x/v1"
    assert local.price_in == 0.0 and local.price_out == 0.0


def test_invalid_tool_rejected():
    with pytest.raises(ValueError):
        ExpertTool(name="x", kind="bogus", backend_type="openai", summary="", model="m")
    with pytest.raises(ValueError):
        ExpertTool(name="x", kind=KIND_MODEL, backend_type="openai", summary="", model=None)


def test_specs_shape_and_pricing_in_description():
    cat = default_catalog()
    specs = build_tool_specs(cat)
    by = {s["function"]["name"]: s for s in specs}
    gpt5 = by["gpt_5"]
    assert gpt5["type"] == "function"
    assert "input" in gpt5["function"]["parameters"]["properties"]
    # Price table is surfaced in the description (the policy is trained on it).
    assert "$1.25/1M input" in gpt5["function"]["description"]
    # Search tool takes a query, code takes code.
    assert "query" in by["web_search"]["function"]["parameters"]["properties"]
    assert "code" in by["code_interpreter"]["function"]["parameters"]["properties"]


def test_sample_is_deterministic_and_well_formed():
    cat = default_catalog(local_model="qwen3:8b", local_endpoint="http://x/v1")
    a = sample_tool_config(cat, rng=random.Random(0), min_tools=4)
    b = sample_tool_config(cat, rng=random.Random(0), min_tools=4)
    assert [t.name for t in a] == [t.name for t in b]  # deterministic
    assert len(a) >= 4
    assert any(t.kind == KIND_MODEL for t in a)         # can reason
    assert any(t.kind != KIND_MODEL for t in a)         # can act
    assert {t.name for t in a} <= {t.name for t in cat}  # subset


def test_price_jitter_changes_prices_reproducibly():
    cat = default_catalog()
    base = {t.name: t for t in sample_tool_config(cat, rng=random.Random(3), min_tools=8)}
    jit = {t.name: t for t in sample_tool_config(
        cat, rng=random.Random(3), min_tools=8, price_jitter=0.5)}
    # Same subset (same seed/sequence up to jitter draws), but model prices move.
    moved = [n for n in base
             if base[n].kind == KIND_MODEL and base[n].price_in
             and n in jit and jit[n].price_in != base[n].price_in]
    assert moved, "expected jitter to change at least one model price"
    for n in moved:
        f = jit[n].price_in / base[n].price_in
        assert 0.5 <= f <= 1.5


# Two cloud-frontier + four local-OSS model tools, in catalog order.
_ORCH_MODEL_NAMES = [
    "gpt_5_5",
    "claude_opus_4_8",
    "qwen3_5_9b",
    "qwen3_6_27b_fp8",
    "qwen3_5_122b_a10b_fp8",
    "qwen3_5_397b_a17b_fp8",
]

# Bridged real OpenJarvis tools (basic) appended after web_search/code_interpreter.
_ORCH_BASIC_NAMES = [
    "web_search",
    "code_interpreter",
    "calculator",
    "shell_exec",
    "file_read",
    "file_write",
    "http_request",
    "think",
    "apply_patch",
    "pdf_extract",
    "db_query",
]


def test_orchestrator_catalog_two_model_classes_plus_basics():
    cat = orchestrator_catalog()
    names = [t.name for t in cat]
    # 6 model tools (2 cloud_frontier + 4 local_oss) come first.
    assert names[:6] == _ORCH_MODEL_NAMES
    # then the basic tools.
    assert set(_ORCH_BASIC_NAMES) <= set(names)
    assert len(cat) == 6 + len(_ORCH_BASIC_NAMES)
    by = tools_by_name(cat)
    assert by["gpt_5_5"].category == CATEGORY_CLOUD_FRONTIER
    assert by["claude_opus_4_8"].category == CATEGORY_CLOUD_FRONTIER
    for n in ("qwen3_5_9b", "qwen3_6_27b_fp8", "qwen3_5_122b_a10b_fp8",
              "qwen3_5_397b_a17b_fp8"):
        assert by[n].category == CATEGORY_LOCAL_OSS
        assert by[n].backend_type == "vllm"
        assert by[n].price_in == 0.0 and by[n].price_out == 0.0


def test_orchestrator_catalog_categories_present():
    cat = orchestrator_catalog()
    cats = {t.category for t in cat}
    assert cats == {CATEGORY_CLOUD_FRONTIER, CATEGORY_LOCAL_OSS, CATEGORY_BASIC}


def test_orchestrator_can_drop_tools():
    cat = orchestrator_catalog(include_tools=False)
    assert {t.category for t in cat} == {CATEGORY_CLOUD_FRONTIER, CATEGORY_LOCAL_OSS}
    assert len(cat) == 6


def test_orchestrator_specs_include_category_field():
    specs = build_tool_specs(orchestrator_catalog())
    by = {s["function"]["name"]: s for s in specs}
    assert by["gpt_5_5"]["function"]["category"] == CATEGORY_CLOUD_FRONTIER
    assert by["qwen3_5_9b"]["function"]["category"] == CATEGORY_LOCAL_OSS
    assert by["web_search"]["function"]["category"] == CATEGORY_BASIC
    assert by["shell_exec"]["function"]["category"] == CATEGORY_BASIC
    # Every tool carries a category tag.
    assert all("category" in s["function"] for s in specs)


def test_orchestrator_local_models_get_base_url_when_provided():
    cat = orchestrator_catalog(
        local_endpoints={
            "Qwen/Qwen3.5-9B": "http://x/v1",
            "Qwen/Qwen3.6-27B-FP8": "http://y/v1",
        })
    by = tools_by_name(cat)
    assert by["qwen3_5_9b"].base_url == "http://x/v1"
    assert by["qwen3_6_27b_fp8"].base_url == "http://y/v1"
    # Unmapped local model -> base_url None.
    assert by["qwen3_5_122b_a10b_fp8"].base_url is None
    # Cloud frontier carries real pricing.
    assert by["claude_opus_4_8"].price_in > 0.0
    assert by["gpt_5_5"].price_in > 0.0


def test_openjarvis_tool_bridges_real_tool_with_custom_schema():
    params = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    }
    t = openjarvis_tool("shell_exec", summary="Run a shell command.", params=params)
    assert t.kind == KIND_TOOL
    assert t.backend_type == "openjarvis-tool"
    assert t.model == "shell_exec"
    assert t.category == CATEGORY_BASIC
    spec = t.to_spec()
    assert spec["function"]["name"] == "shell_exec"
    assert spec["function"]["parameters"] == params
    assert spec["function"]["category"] == CATEGORY_BASIC


def test_build_tool_specs_includes_category_for_bridged_tools():
    specs = build_tool_specs([
        openjarvis_tool("calculator", summary="Math.",
                        params={"type": "object",
                                "properties": {"expression": {"type": "string"}},
                                "required": ["expression"]}),
    ])
    assert specs[0]["function"]["category"] == CATEGORY_BASIC
    assert "expression" in specs[0]["function"]["parameters"]["properties"]


def test_to_worker_dict_maps_backend():
    cat = default_catalog(local_model="qwen3:8b", local_endpoint="http://x/v1")
    by = tools_by_name(cat)
    assert to_worker_dict(by["gpt_5"]) == {
        "name": "gpt_5", "type": "openai", "model": "gpt-5"}
    local = to_worker_dict(by["qwen3_8b"])
    assert local["type"] == "vllm" and local["base_url"] == "http://x/v1"

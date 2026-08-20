"""browser_assistant dataset — 30 web research tasks.

Each task provides a research question with verifiable facts tagged as
`exact` (string/number match) or `semantic` (LLM judge needed).

Difficulty tiers:
- easy (10): single factual lookup
- medium (10): comparison or multi-fact research
- hard (10): complex synthesis requiring multiple sources
"""

from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """You are a web research assistant. Answer the following question accurately and cite your sources.

## Question
{question}

Provide a clear, factual answer with specific numbers, names, or details where applicable. Include source references."""

# ---------------------------------------------------------------------------
# EASY tasks (10): single factual lookup
# ---------------------------------------------------------------------------

_EASY_TASKS: List[Dict[str, Any]] = [
    {
        "question": "What is the maximum context length of Llama 3.1 405B?",
        "expected_facts": [
            {"fact": "128K tokens", "type": "exact"},
        ],
    },
    {
        "question": "Which NVIDIA GPU has the highest memory bandwidth in the H-series?",
        "expected_facts": [
            {"fact": "H200", "type": "exact"},
            {"fact": "4.8 TB/s", "type": "exact"},
        ],
    },
    {
        "question": "What programming language is Redis written in?",
        "expected_facts": [
            {"fact": "C", "type": "exact"},
        ],
    },
    {
        "question": "What is the default port for PostgreSQL?",
        "expected_facts": [
            {"fact": "5432", "type": "exact"},
        ],
    },
    {
        "question": "Who created the Python programming language?",
        "expected_facts": [
            {"fact": "Guido van Rossum", "type": "exact"},
        ],
    },
    {
        "question": "What is the maximum number of GPUs supported in a single NVIDIA DGX H100 system?",
        "expected_facts": [
            {"fact": "8", "type": "exact"},
        ],
    },
    {
        "question": "What license is the Linux kernel released under?",
        "expected_facts": [
            {"fact": "GPL-2.0", "type": "exact"},
        ],
    },
    {
        "question": "What is the default isolation level in PostgreSQL?",
        "expected_facts": [
            {"fact": "Read Committed", "type": "exact"},
        ],
    },
    {
        "question": "How many attention heads does GPT-4 use (as reported in public documentation)?",
        "expected_facts": [
            {
                "fact": "architecture details not publicly disclosed by OpenAI",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "What year was Kubernetes first released?",
        "expected_facts": [
            {"fact": "2014", "type": "exact"},
        ],
    },
]

# ---------------------------------------------------------------------------
# MEDIUM tasks (10): comparison or multi-fact research
# ---------------------------------------------------------------------------

_MEDIUM_TASKS: List[Dict[str, Any]] = [
    {
        "question": "Compare the context window sizes of Claude 3.5 Sonnet, GPT-4 Turbo, and Gemini 1.5 Pro.",
        "expected_facts": [
            {"fact": "Claude 3.5 Sonnet: 200K tokens", "type": "exact"},
            {"fact": "GPT-4 Turbo: 128K tokens", "type": "exact"},
            {"fact": "Gemini 1.5 Pro: 1M+ tokens", "type": "exact"},
        ],
    },
    {
        "question": "What are the key differences between Qdrant and Weaviate for vector search?",
        "expected_facts": [
            {"fact": "Qdrant uses Rust, Weaviate uses Go", "type": "semantic"},
            {"fact": "both support filtering with vector search", "type": "semantic"},
            {"fact": "differences in multi-tenancy support", "type": "semantic"},
        ],
    },
    {
        "question": "Compare vLLM and TensorRT-LLM for serving large language models.",
        "expected_facts": [
            {
                "fact": "vLLM uses PagedAttention for memory efficiency",
                "type": "semantic",
            },
            {
                "fact": "TensorRT-LLM optimizes for NVIDIA GPUs specifically",
                "type": "semantic",
            },
            {
                "fact": "vLLM is easier to set up, TensorRT-LLM has higher throughput on supported hardware",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "What are the memory requirements for running Llama 3.1 70B at FP16 vs INT8 vs INT4?",
        "expected_facts": [
            {"fact": "FP16: approximately 140GB", "type": "exact"},
            {"fact": "INT8: approximately 70GB", "type": "exact"},
            {"fact": "INT4: approximately 35GB", "type": "exact"},
        ],
    },
    {
        "question": "Compare PostgreSQL and MySQL for JSON document storage.",
        "expected_facts": [
            {"fact": "PostgreSQL has JSONB with GIN indexes", "type": "semantic"},
            {
                "fact": "MySQL has JSON type with generated columns for indexing",
                "type": "semantic",
            },
            {
                "fact": "PostgreSQL JSONB is generally more feature-rich for JSON operations",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "What are the differences between Docker and Podman?",
        "expected_facts": [
            {"fact": "Podman is daemonless", "type": "semantic"},
            {"fact": "Podman runs rootless by default", "type": "semantic"},
            {
                "fact": "Docker uses a client-server architecture with dockerd",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "Compare Terraform and Pulumi for infrastructure as code.",
        "expected_facts": [
            {
                "fact": "Terraform uses HCL, Pulumi uses general-purpose languages",
                "type": "semantic",
            },
            {"fact": "both support multiple cloud providers", "type": "semantic"},
            {
                "fact": "Pulumi has native support for Python, TypeScript, Go, C#",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "What are the CUDA compute capabilities of NVIDIA A100, H100, and H200?",
        "expected_facts": [
            {"fact": "A100: compute capability 8.0", "type": "exact"},
            {"fact": "H100: compute capability 9.0", "type": "exact"},
            {"fact": "H200: compute capability 9.0", "type": "exact"},
        ],
    },
    {
        "question": "Compare FastAPI, Flask, and Django for building REST APIs.",
        "expected_facts": [
            {
                "fact": "FastAPI is async-first with automatic OpenAPI docs",
                "type": "semantic",
            },
            {"fact": "Flask is lightweight and flexible", "type": "semantic"},
            {
                "fact": "Django includes ORM, admin, and batteries-included approach",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "What embedding dimensions do OpenAI text-embedding-3-small and text-embedding-3-large support?",
        "expected_facts": [
            {"fact": "text-embedding-3-small: 1536 dimensions", "type": "exact"},
            {"fact": "text-embedding-3-large: 3072 dimensions", "type": "exact"},
        ],
    },
]

# ---------------------------------------------------------------------------
# HARD tasks (10): complex synthesis
# ---------------------------------------------------------------------------

_HARD_TASKS: List[Dict[str, Any]] = [
    {
        "question": "What is the current state of the art for code generation benchmarks (HumanEval, MBPP)? Which models lead and what are their scores?",
        "expected_facts": [
            {"fact": "recent top models score 90%+ on HumanEval", "type": "semantic"},
            {
                "fact": "MBPP scores are generally lower than HumanEval",
                "type": "semantic",
            },
            {"fact": "mentions specific model names and scores", "type": "semantic"},
        ],
    },
    {
        "question": "Explain the trade-offs between different attention mechanisms: multi-head attention, grouped-query attention, and multi-query attention.",
        "expected_facts": [
            {
                "fact": "MHA uses separate K,V heads per attention head",
                "type": "semantic",
            },
            {
                "fact": "GQA groups multiple query heads to share K,V heads",
                "type": "semantic",
            },
            {
                "fact": "MQA uses single K,V head for all query heads",
                "type": "semantic",
            },
            {"fact": "GQA balances quality and inference speed", "type": "semantic"},
        ],
    },
    {
        "question": "What are the latest developments in mixture-of-experts (MoE) architectures for LLMs? Compare Mixtral, DeepSeek-V2, and Grok-1.",
        "expected_facts": [
            {
                "fact": "Mixtral 8x7B routes to 2 of 8 experts per token",
                "type": "semantic",
            },
            {
                "fact": "DeepSeek-V2 uses fine-grained expert segmentation",
                "type": "semantic",
            },
            {
                "fact": "MoE reduces compute cost per token vs dense models",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "How do different quantization methods (GPTQ, AWQ, GGUF/GGML, bitsandbytes) compare for LLM inference?",
        "expected_facts": [
            {
                "fact": "GPTQ uses post-training quantization with calibration data",
                "type": "semantic",
            },
            {
                "fact": "AWQ preserves salient weights for better quality",
                "type": "semantic",
            },
            {
                "fact": "GGUF is the llama.cpp format for CPU and mixed inference",
                "type": "semantic",
            },
            {"fact": "bitsandbytes supports QLoRA for fine-tuning", "type": "semantic"},
        ],
    },
    {
        "question": "What are the security implications of running LLMs in production? Cover prompt injection, data exfiltration, and model poisoning.",
        "expected_facts": [
            {"fact": "prompt injection can bypass system prompts", "type": "semantic"},
            {
                "fact": "data exfiltration via tool use or function calling",
                "type": "semantic",
            },
            {
                "fact": "model poisoning through training data contamination",
                "type": "semantic",
            },
            {
                "fact": "mitigations include input filtering and output scanning",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "Compare the architectures and capabilities of major embedding models: OpenAI ada-002/3, Cohere embed-v3, and open-source alternatives like BGE and E5.",
        "expected_facts": [
            {
                "fact": "OpenAI text-embedding-3 supports Matryoshka dimensions",
                "type": "semantic",
            },
            {
                "fact": "Cohere embed-v3 supports multiple input types",
                "type": "semantic",
            },
            {
                "fact": "BGE and E5 are open-source alternatives with competitive performance",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "What is the current landscape of AI chip competition? Compare NVIDIA H100/H200, AMD MI300X, Google TPU v5, and Intel Gaudi 3.",
        "expected_facts": [
            {"fact": "H100 has 80GB HBM3", "type": "semantic"},
            {"fact": "MI300X has 192GB HBM3", "type": "semantic"},
            {"fact": "TPU v5 designed for large-scale training", "type": "semantic"},
            {"fact": "NVIDIA dominates market share", "type": "semantic"},
        ],
    },
    {
        "question": "How do different RAG (Retrieval-Augmented Generation) strategies compare? Cover naive RAG, advanced RAG with re-ranking, and GraphRAG.",
        "expected_facts": [
            {
                "fact": "naive RAG does simple similarity search then generate",
                "type": "semantic",
            },
            {
                "fact": "re-ranking improves retrieval precision with cross-encoder",
                "type": "semantic",
            },
            {
                "fact": "GraphRAG uses knowledge graphs for structured retrieval",
                "type": "semantic",
            },
            {
                "fact": "hybrid search combines dense and sparse retrieval",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "What are the key differences between LoRA, QLoRA, DoRA, and full fine-tuning for LLMs?",
        "expected_facts": [
            {"fact": "LoRA adds low-rank adapter matrices", "type": "semantic"},
            {"fact": "QLoRA combines quantization with LoRA", "type": "semantic"},
            {
                "fact": "DoRA decomposes weights into magnitude and direction",
                "type": "semantic",
            },
            {
                "fact": "full fine-tuning updates all parameters but needs more memory",
                "type": "semantic",
            },
        ],
    },
    {
        "question": "Explain the evolution of position encoding in transformers: absolute, RoPE, ALiBi, and YaRN. What are the trade-offs for long-context extension?",
        "expected_facts": [
            {
                "fact": "absolute position embeddings are fixed length",
                "type": "semantic",
            },
            {
                "fact": "RoPE encodes relative position through rotation",
                "type": "semantic",
            },
            {"fact": "ALiBi adds linear bias to attention scores", "type": "semantic"},
            {
                "fact": "YaRN extends context through interpolation of RoPE",
                "type": "semantic",
            },
        ],
    },
]


class BrowserAssistantDataset(DatasetProvider):
    """30 web research tasks with verifiable facts."""

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: str = "test",
        seed: Optional[int] = None,
    ) -> None:
        all_tasks = _EASY_TASKS + _MEDIUM_TASKS + _HARD_TASKS
        difficulties = (
            ["easy"] * len(_EASY_TASKS)
            + ["medium"] * len(_MEDIUM_TASKS)
            + ["hard"] * len(_HARD_TASKS)
        )

        paired = list(zip(all_tasks, difficulties))
        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(paired)

        if max_samples is not None:
            paired = paired[:max_samples]

        self._records: List[EvalRecord] = []
        for idx, (task, diff) in enumerate(paired):
            prompt = _PROMPT_TEMPLATE.format(
                question=task["question"],
            )

            exact_facts = [
                f["fact"] for f in task["expected_facts"] if f["type"] == "exact"
            ]
            semantic_facts = [
                f["fact"] for f in task["expected_facts"] if f["type"] == "semantic"
            ]

            self._records.append(
                EvalRecord(
                    record_id=f"browser-assistant-{idx:03d}",
                    problem=prompt,
                    reference="; ".join(f["fact"] for f in task["expected_facts"]),
                    category="agentic",
                    subject=diff,
                    metadata={
                        "question": task["question"],
                        "expected_facts": task["expected_facts"],
                        "exact_facts": exact_facts,
                        "semantic_facts": semantic_facts,
                    },
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["BrowserAssistantDataset"]

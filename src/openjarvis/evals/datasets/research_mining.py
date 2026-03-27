"""Research mining benchmark dataset.

Research questions spanning multiple domains for evaluating synthesis,
source quality, and accuracy of AI research assistants.
"""

from __future__ import annotations

import random
from typing import Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """You are a research assistant. Please research the following question and provide a comprehensive answer.

Your response should include:
1. Key findings (3-5 main points)
2. Supporting evidence or data
3. A synthesis paragraph connecting the findings

Research question: {question}
Domain: {domain}
Scope: {scope}"""

_QUESTIONS = [
    {
        "question": "What are the main approaches to running large language models on consumer hardware, and what trade-offs does each approach involve?",
        "domain": "AI/ML",
        "scope": "Technical survey",
        "key_facts": "quantization (GPTQ, AWQ, GGUF), distillation, pruning, speculative decoding, offloading; trade-offs include accuracy loss vs speed gain vs memory reduction",
    },
    {
        "question": "How does the energy consumption of cloud-based AI inference compare to on-device inference for typical consumer workloads?",
        "domain": "Energy/Sustainability",
        "scope": "Comparative analysis",
        "key_facts": "cloud inference involves network transfer, datacenter cooling, shared GPU utilization; on-device avoids network overhead but may use less efficient hardware; total energy depends on workload volume and hardware",
    },
    {
        "question": "What are the privacy implications of sending personal data to cloud AI services versus processing it locally?",
        "domain": "Privacy/Security",
        "scope": "Policy analysis",
        "key_facts": "data exposure in transit and at rest, third-party access, GDPR/CCPA compliance, data retention policies, local processing eliminates transmission risk",
    },
    {
        "question": "What mechanisms exist for retrieval-augmented generation (RAG) and how do they compare in accuracy and latency?",
        "domain": "AI/ML",
        "scope": "Technical comparison",
        "key_facts": "dense retrieval (DPR, ColBERT), sparse retrieval (BM25), hybrid approaches (RRF fusion), chunk size effects, re-ranking strategies, context window limits",
    },
    {
        "question": "What is the current state of hardware acceleration for AI inference on consumer devices?",
        "domain": "Hardware",
        "scope": "Market survey",
        "key_facts": "NVIDIA consumer GPUs (RTX series), Apple Silicon (M-series Neural Engine), AMD GPUs (ROCm), Intel Arc, Qualcomm NPUs, VRAM as primary bottleneck",
    },
    {
        "question": "How do different model quantization methods affect inference quality for code generation tasks?",
        "domain": "AI/ML",
        "scope": "Empirical analysis",
        "key_facts": "INT8, INT4, FP8, GPTQ vs AWQ vs GGUF; code generation sensitive to quantization; larger models tolerate more aggressive quantization; benchmark results vary by task complexity",
    },
    {
        "question": "What are the economic factors driving the shift from cloud AI services to on-premises or local AI deployments?",
        "domain": "Economics",
        "scope": "Market analysis",
        "key_facts": "API cost escalation, GPU cost amortization, regulatory compliance costs, data sovereignty requirements, latency-sensitive applications, predictable vs variable costs",
    },
    {
        "question": "How effective are agent-based AI systems at automating software engineering tasks?",
        "domain": "Software Engineering",
        "scope": "Research survey",
        "key_facts": "SWE-bench results, agentic loop patterns (ReAct, CodeAct), tool use, multi-step reasoning, error recovery, cost per task solved, current accuracy limitations",
    },
    {
        "question": "What role does knowledge graph technology play in improving AI system accuracy and explainability?",
        "domain": "AI/Knowledge Management",
        "scope": "Technical survey",
        "key_facts": "entity-relation storage, graph-augmented retrieval, fact verification, reasoning chains, hybrid approaches with vector databases, explainable AI connections",
    },
    {
        "question": "What are the best practices for evaluating LLM performance across diverse task categories?",
        "domain": "AI Evaluation",
        "scope": "Methodological survey",
        "key_facts": "benchmark suites (MMLU, GPQA, HLE), LLM-as-judge, human evaluation, contamination concerns, multi-dimensional scoring, statistical significance testing",
    },
    {
        "question": "How can scheduled AI agents reduce operational costs for routine business tasks?",
        "domain": "Business Automation",
        "scope": "Practical analysis",
        "key_facts": "cron-based scheduling, email triage automation, report generation, monitoring/alerting, cost comparison vs human labor vs cloud API calls",
    },
    {
        "question": "What is the environmental impact of training and deploying large language models?",
        "domain": "Sustainability",
        "scope": "Impact assessment",
        "key_facts": "training carbon footprint, inference energy per query, datacenter water usage, hardware lifecycle, renewable energy offsets, efficiency improvements over time",
    },
    {
        "question": "How do different memory architectures in AI assistants affect long-term user experience?",
        "domain": "Human-Computer Interaction",
        "scope": "Design analysis",
        "key_facts": "session-based vs persistent memory, vector similarity search, knowledge graph memory, decay and consolidation, privacy controls, user trust",
    },
    {
        "question": "What security vulnerabilities are unique to AI-powered applications?",
        "domain": "Cybersecurity",
        "scope": "Threat analysis",
        "key_facts": "prompt injection, jailbreaking, data exfiltration via LLM, model inversion, supply chain attacks on model weights, PII leakage, SSRF via tool calls",
    },
    {
        "question": "How do open-source and proprietary AI models compare for enterprise deployment?",
        "domain": "Enterprise AI",
        "scope": "Comparative analysis",
        "key_facts": "licensing terms, customization flexibility, support and SLA, total cost of ownership, data privacy, model quality trends, community ecosystem",
    },
    {
        "question": "What approaches exist for making AI systems more energy-efficient during inference?",
        "domain": "Green AI",
        "scope": "Technical survey",
        "key_facts": "model pruning, quantization, speculative decoding, dynamic batching, hardware-software co-design, early exit strategies, mixture of experts",
    },
    {
        "question": "How can AI assistants effectively manage multi-channel communication across platforms like Slack, email, and messaging apps?",
        "domain": "Communication Systems",
        "scope": "Architecture analysis",
        "key_facts": "channel abstraction, unified session identity, message routing, webhook vs polling, rate limiting, cross-channel context, user preference management",
    },
    {
        "question": "What are the current limitations and future directions of on-device speech recognition?",
        "domain": "Speech Processing",
        "scope": "Technology assessment",
        "key_facts": "Whisper variants, CTranslate2 optimization, streaming vs batch, vocabulary and language coverage, noise robustness, privacy benefits, latency requirements",
    },
    {
        "question": "How do workflow engines and DAG-based execution improve AI agent reliability?",
        "domain": "AI Systems",
        "scope": "Architecture survey",
        "key_facts": "directed acyclic graphs, topological sort, parallel execution, error recovery, conditional branching, checkpointing, loop detection, human-in-the-loop gates",
    },
    {
        "question": "What is the role of telemetry and observability in production AI systems?",
        "domain": "MLOps",
        "scope": "Best practices survey",
        "key_facts": "token usage tracking, latency monitoring, cost attribution, energy measurement, model drift detection, alert thresholds, privacy-preserving telemetry",
    },
    {
        "question": "How can reinforcement learning improve AI agent decision-making in real-time applications?",
        "domain": "AI/ML",
        "scope": "Research survey",
        "key_facts": "GRPO, bandit algorithms (Thompson Sampling, UCB1), reward shaping, sample efficiency, exploration vs exploitation, online vs offline RL, safety constraints",
    },
    {
        "question": "What are the emerging standards and protocols for AI agent interoperability?",
        "domain": "AI Standards",
        "scope": "Standards review",
        "key_facts": "MCP (Model Context Protocol), A2A (Agent-to-Agent), OpenAI function calling, tool use formats, JSON-RPC, agent card discovery, capability negotiation",
    },
    {
        "question": "How does the Model Context Protocol (MCP) enable extensible tool integration in AI systems?",
        "domain": "AI Infrastructure",
        "scope": "Technical analysis",
        "key_facts": "JSON-RPC 2.0, tools/list and tools/call, server discovery, template-based tool generation, security considerations, adapter patterns, community ecosystem",
    },
    {
        "question": "What strategies exist for preventing and detecting AI hallucinations in production systems?",
        "domain": "AI Safety",
        "scope": "Technical survey",
        "key_facts": "retrieval augmentation, chain-of-thought verification, self-consistency checking, confidence calibration, knowledge grounding, citation generation, human review loops",
    },
    {
        "question": "How do edge computing and on-device AI complement each other for IoT applications?",
        "domain": "Edge Computing",
        "scope": "Architecture analysis",
        "key_facts": "latency requirements, bandwidth constraints, intermittent connectivity, model size limits, federated learning, privacy preservation, hardware heterogeneity",
    },
    {
        "question": "What approaches exist for cost-effective fine-tuning of language models on domain-specific data?",
        "domain": "AI/ML",
        "scope": "Practical guide",
        "key_facts": "LoRA, QLoRA, prefix tuning, adapter methods, data quality over quantity, synthetic data generation, evaluation methodology, compute budgeting",
    },
    {
        "question": "How can AI systems maintain consistency and accuracy across multi-turn conversations?",
        "domain": "Conversational AI",
        "scope": "Technical analysis",
        "key_facts": "context window management, session persistence, fact tracking, contradiction detection, memory consolidation, user modeling, conversation summarization",
    },
    {
        "question": "What are the trade-offs between different vector database implementations for AI memory systems?",
        "domain": "Data Infrastructure",
        "scope": "Comparative analysis",
        "key_facts": "FAISS vs Chroma vs Weaviate vs Qdrant, indexing speed, query latency, memory footprint, scalability, filtering, hybrid search, SQLite/FTS5 as lightweight alternative",
    },
    {
        "question": "How do capability-based access control and taint tracking improve AI system security?",
        "domain": "AI Security",
        "scope": "Architecture analysis",
        "key_facts": "RBAC vs capability model, principle of least privilege, taint propagation, sink policies, audit logging, Merkle chains for tamper evidence, tool-level enforcement",
    },
    {
        "question": "What metrics best capture the efficiency of AI inference in terms of intelligence per resource consumed?",
        "domain": "AI Evaluation",
        "scope": "Metrics design",
        "key_facts": "Intelligence Per Watt (IPW), Intelligence Per Joule (IPJ), tokens per second per watt, accuracy per dollar, MFU/MBU, energy per output token, steady-state detection",
    },
    {
        "question": "How can desktop AI applications provide a seamless user experience while managing local compute resources?",
        "domain": "Desktop Applications",
        "scope": "UX/Architecture analysis",
        "key_facts": "Tauri/Electron frameworks, background service management, resource monitoring, model switching, system tray integration, auto-start, update mechanisms",
    },
]


class ResearchMiningDataset(DatasetProvider):
    """Research mining benchmark: evaluate research synthesis and accuracy."""

    dataset_id = "research_mining"
    dataset_name = "Research Mining"

    def __init__(self) -> None:
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        rows = list(_QUESTIONS)

        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        self._records = []
        for idx, q in enumerate(rows):
            prompt = _PROMPT_TEMPLATE.format(
                question=q["question"],
                domain=q["domain"],
                scope=q["scope"],
            )
            self._records.append(
                EvalRecord(
                    record_id=f"research-mining-{idx}",
                    problem=prompt,
                    reference=q["key_facts"],
                    category="use-case",
                    subject="research_mining",
                    metadata={"domain": q["domain"], "scope": q["scope"]},
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["ResearchMiningDataset"]

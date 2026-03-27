"""Knowledge base benchmark dataset.

Document-grounded retrieval questions for evaluating retrieval accuracy
and answer correctness from a knowledge corpus.
"""

from __future__ import annotations

import random
from typing import Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """You are a knowledge base assistant. Answer the following question using only the information provided in the document excerpts below. If the answer cannot be determined from the documents, say "Cannot be determined from the provided documents."

Documents:
{documents}

Question: {question}

Provide a concise, accurate answer based solely on the documents above."""

_RECORDS = [
    {
        "documents": "OpenJarvis Architecture Guide (v2.9):\nOpenJarvis is organized around five composable primitives: Intelligence, Engine, Agents, Tools, and Learning. The Intelligence primitive handles model definition and catalog management via ModelRegistry. The Engine primitive provides inference through backends including Ollama, vLLM, SGLang, llama.cpp, MLX, and LM Studio. All engines implement the InferenceEngine ABC with generate(), stream(), list_models(), and health() methods.",
        "question": "What are the five primitives of OpenJarvis and what does the Engine primitive provide?",
        "answer": "The five primitives are Intelligence, Engine, Agents, Tools, and Learning. The Engine primitive provides inference through backends including Ollama, vLLM, SGLang, llama.cpp, MLX, and LM Studio.",
    },
    {
        "documents": "Memory Backend Comparison (Internal Doc):\nSQLite/FTS5 is the default memory backend, providing full-text search with minimal dependencies. FAISS offers dense vector similarity search suitable for semantic retrieval. ColBERTv2 provides late-interaction retrieval with higher accuracy but requires more compute. BM25 is a traditional sparse retrieval method. The Hybrid backend uses Reciprocal Rank Fusion (RRF) to combine results from multiple backends.",
        "question": "What is the default memory backend and how does the Hybrid backend combine results?",
        "answer": "SQLite/FTS5 is the default memory backend. The Hybrid backend uses Reciprocal Rank Fusion (RRF) to combine results from multiple backends.",
    },
    {
        "documents": "Security Architecture Document:\nOpenJarvis implements a multi-layer security approach. SecretScanner and PIIScanner implement the BaseScanner ABC. GuardrailsEngine wraps inference engines with input/output scanning supporting WARN, REDACT, and BLOCK modes. The AuditLogger uses a Merkle hash chain with SHA-256 for tamper evidence. CapabilityPolicy provides RBAC with 10 capabilities and glob matching, enforced in ToolExecutor.",
        "question": "How does the AuditLogger ensure tamper evidence?",
        "answer": "The AuditLogger uses a Merkle hash chain with SHA-256 for tamper evidence.",
    },
    {
        "documents": "Agent System Documentation:\nOpenJarvis agents follow a hierarchy: BaseAgent ABC provides helpers for turn management and message building. ToolUsingAgent extends BaseAgent with tool dispatch via ToolExecutor. SimpleAgent handles single-turn queries. OrchestratorAgent manages multi-turn tool loops. NativeReActAgent implements Thought-Action-Observation patterns. The LoopGuard system prevents infinite loops via SHA-256 hash tracking and ping-pong detection.",
        "question": "What is the agent hierarchy and how are infinite loops prevented?",
        "answer": "The hierarchy is BaseAgent -> ToolUsingAgent -> specific agents (SimpleAgent, OrchestratorAgent, NativeReActAgent, etc.). Infinite loops are prevented by the LoopGuard system which uses SHA-256 hash tracking and ping-pong detection.",
    },
    {
        "documents": "Telemetry System Guide:\nInstrumentedEngine wraps any inference engine to collect telemetry transparently. TelemetryStore persists records to SQLite. TelemetryAggregator provides read-only queries for statistics. EnergyMonitor ABC has vendor-specific implementations: NvidiaEnergyMonitor (hardware counters/polling), AmdEnergyMonitor (amdsmi), AppleEnergyMonitor (zeus-ml), and RaplEnergyMonitor (sysfs). EnergyBatch tracks batch-level energy-per-token metrics.",
        "question": "What energy monitoring backends are available and what library does the Apple backend use?",
        "answer": "The available energy monitoring backends are NvidiaEnergyMonitor (hardware counters/polling), AmdEnergyMonitor (amdsmi), AppleEnergyMonitor (zeus-ml), and RaplEnergyMonitor (sysfs). The Apple backend uses the zeus-ml library.",
    },
    {
        "documents": "Configuration Reference:\nOpenJarvis uses TOML configuration with primitive-aligned sections. The config file is located at ~/.openjarvis/config.toml. Key sections include [engine] with nested per-backend configs (e.g., [engine.ollama], [engine.vllm]), [intelligence] for model defaults, [agent] for agent configuration, [tools.storage] for memory backend settings, [learning] with nested routing/intelligence/agent/metrics sub-policies, and [security] with capabilities and rate limiting.",
        "question": "Where is the config file located and what format does it use?",
        "answer": "The config file is located at ~/.openjarvis/config.toml and uses TOML format.",
    },
    {
        "documents": "Learning Subsystem Overview:\nThe Learning primitive supports multiple routing policies. HeuristicRouter uses rule-based routing. SFTRouterPolicy learns query-to-model mapping from traces. GRPORouterPolicy uses softmax sampling with group relative advantage and per-query-class weights. BanditRouterPolicy implements Thompson Sampling and UCB1 with per-arm statistics. SkillDiscovery mines tool subsequences from traces to auto-generate skill manifests.",
        "question": "What routing policies are available and what algorithm does BanditRouterPolicy implement?",
        "answer": "Available routing policies are HeuristicRouter, SFTRouterPolicy, GRPORouterPolicy, and BanditRouterPolicy. BanditRouterPolicy implements Thompson Sampling and UCB1 algorithms.",
    },
    {
        "documents": "MCP Integration Guide:\nThe Model Context Protocol (MCP) is used for all tool management. MCPToolAdapter wraps external MCP tools as native BaseTool instances. MCPToolProvider discovers tools from MCP servers. The built-in MCP server exposes all tools via JSON-RPC tools/list and tools/call endpoints following the MCP spec 2025-11-25. Tool templates in tools/templates/ allow dynamic tool construction from TOML specifications with 10 builtin templates.",
        "question": "How does OpenJarvis integrate with external MCP tools?",
        "answer": "MCPToolAdapter wraps external MCP tools as native BaseTool instances, and MCPToolProvider discovers tools from MCP servers.",
    },
    {
        "documents": "Workflow Engine Documentation:\nThe workflow engine uses DAG-based WorkflowGraph with cycle detection and topological sort. Parallel stages execute via ThreadPoolExecutor. WorkflowBuilder provides a fluent API for graph construction. WorkflowEngine executes workflows against a JarvisSystem instance. Workflows can be defined in TOML files. Supported node types: agent, tool, condition, parallel, loop, and transform.",
        "question": "What node types does the workflow engine support and how are parallel stages executed?",
        "answer": "The workflow engine supports agent, tool, condition, parallel, loop, and transform node types. Parallel stages are executed via ThreadPoolExecutor.",
    },
    {
        "documents": "Speech Subsystem Technical Reference:\nOpenJarvis supports speech-to-text with pluggable backends. SpeechBackend ABC defines transcribe(), health(), and supported_formats() methods. Three backends are available: FasterWhisperBackend (local, CTranslate2, key 'faster-whisper'), OpenAIWhisperBackend (cloud, whisper-1, key 'openai'), and DeepgramSpeechBackend (cloud, nova-2, key 'deepgram'). Auto-discovery prioritizes local backends.",
        "question": "What speech backends are available and which models do the cloud backends use?",
        "answer": "Three backends are available: FasterWhisperBackend (local), OpenAIWhisperBackend (cloud, using whisper-1), and DeepgramSpeechBackend (cloud, using nova-2). Auto-discovery prioritizes local backends.",
    },
    {
        "documents": "Sandbox System Guide:\nOpenJarvis provides two sandbox options. ContainerRunner manages Docker/Podman container lifecycle with mount validation. WasmRunner uses wasmtime-py with fuel and memory limits. SandboxedAgent is a transparent wrapper that routes agent execution through either sandbox. MountAllowlist prevents path traversal attacks. The create_sandbox_runner() factory selects the appropriate runner.",
        "question": "What are the two sandbox options and what prevents path traversal attacks?",
        "answer": "The two sandbox options are ContainerRunner (Docker/Podman) and WasmRunner (wasmtime-py). MountAllowlist prevents path traversal attacks.",
    },
    {
        "documents": "Channel System Architecture:\nOpenJarvis supports multi-platform messaging via the BaseChannel ABC. Available channels include WhatsAppBaileysChannel, LINEChannel, ViberChannel, MessengerChannel, RedditChannel, MastodonChannel, XMPPChannel, RocketChatChannel, ZulipChannel, TwitchChannel, and NostrChannel. All channels use @ChannelRegistry.register() for discovery and integrate with the EventBus.",
        "question": "How many messaging channels does OpenJarvis support and how are they discovered?",
        "answer": "OpenJarvis supports 11 messaging channels. They are discovered via the @ChannelRegistry.register() decorator.",
    },
    {
        "documents": "Eval Framework Guide:\nThe evaluation framework includes 15 real benchmark datasets from IPW: SuperGPQA, GPQA, MMLU-Pro, MATH-500, Natural Reasoning, HLE, SimpleQA, WildChat, IPW, GAIA, FRAMES, SWE-bench, SWEfficiency, TerminalBench, and TerminalBench Native. Scorer types include MCQ letter extraction, LLM-judge, exact match, and structural validation. EvalRunner supports parallel execution.",
        "question": "How many benchmark datasets are available and what scorer types exist?",
        "answer": "There are 15 benchmark datasets available. Scorer types include MCQ letter extraction, LLM-judge, exact match, and structural validation.",
    },
    {
        "documents": "Session Management Documentation:\nSessionStore uses SQLite for cross-channel persistent sessions. SessionIdentity provides canonical user identification across channels. The consolidate() method summarizes old messages to reduce storage. The decay() method removes expired sessions based on configurable retention policies.",
        "question": "How are sessions managed across channels and how is storage reduced?",
        "answer": "Sessions are managed via SessionStore using SQLite with SessionIdentity for canonical user identification across channels. Storage is reduced through the consolidate() method which summarizes old messages.",
    },
    {
        "documents": "Desktop Application Guide:\nThe OpenJarvis desktop app uses Tauri 2.0. It includes 5 dashboard panels: EnergyDashboard (real-time power monitoring with recharts), TraceDebugger (timeline inspection with step-type color coding), LearningCurve (policy visualization for GRPO/bandit stats), MemoryBrowser (search and stats), and AdminPanel (health, agents, server control). Tauri commands proxy to the OpenJarvis REST API.",
        "question": "What framework does the desktop app use and what are the 5 dashboard panels?",
        "answer": "The desktop app uses Tauri 2.0. The 5 panels are EnergyDashboard, TraceDebugger, LearningCurve, MemoryBrowser, and AdminPanel.",
    },
    {
        "documents": "API Server Reference:\nThe OpenAI-compatible server is started via 'jarvis serve'. Core endpoints: POST /v1/chat/completions, GET /v1/models, GET /health. Extended endpoints cover agents, memory, traces, telemetry, learning, skills, sessions, budget, and metrics. SSE streaming is supported on /v1/chat/completions with stream=true. WebSocket streaming is available at WS /v1/chat/stream.",
        "question": "How is the API server started and what streaming options are available?",
        "answer": "The API server is started via 'jarvis serve'. SSE streaming is available on /v1/chat/completions with stream=true, and WebSocket streaming is available at WS /v1/chat/stream.",
    },
    {
        "documents": "Trace System Documentation:\nTraces capture full interaction records via TraceStep objects. Step types include route, retrieve, generate, tool_call, and respond, each with timing information. TraceStore persists traces to SQLite. TraceCollector auto-wraps agents to capture traces. TraceAnalyzer generates statistics used by the learning subsystem.",
        "question": "What step types can a trace contain and how are traces used for learning?",
        "answer": "Traces can contain route, retrieve, generate, tool_call, and respond steps. TraceAnalyzer generates statistics from traces that are used by the learning subsystem.",
    },
    {
        "documents": "Skill System Reference:\nSkills are defined as TOML manifests with sequential tool steps and template rendering. SkillExecutor runs the steps in order. Ed25519 signature verification ensures skill integrity. SkillTool adapter wraps skills as invocable tools. There are 20 bundled skills covering file management, research, code quality, productivity, and document processing.",
        "question": "How many bundled skills are there and how is their integrity verified?",
        "answer": "There are 20 bundled skills. Their integrity is verified through Ed25519 signature verification.",
    },
    {
        "documents": "Vault System Guide:\nThe vault provides encrypted credential storage at ~/.openjarvis/vault.enc using Fernet encryption. The encryption key is auto-generated with 0o600 file permissions for security. CLI commands: 'jarvis vault set KEY' to store, 'jarvis vault get KEY' to retrieve, and 'jarvis vault list' to list stored keys.",
        "question": "What encryption does the vault use and where is it stored?",
        "answer": "The vault uses Fernet encryption and is stored at ~/.openjarvis/vault.enc.",
    },
    {
        "documents": "Recipe System Documentation:\nRecipes are composable TOML configs that wire all 5 primitives. Each Recipe dataclass provides to_builder_kwargs() for SystemBuilder integration. Three built-in recipes exist: coding_assistant, research_assistant, and general_assistant. Operator recipes include researcher (4h cycle), correspondent (5min interval), and sentinel (2h cycle). Recipes are discovered via discover_recipes() and resolved via resolve_recipe().",
        "question": "What built-in recipes exist and what are the operator recipe cycle times?",
        "answer": "Built-in recipes are coding_assistant, research_assistant, and general_assistant. Operator recipe cycle times: researcher (4h), correspondent (5min), sentinel (2h).",
    },
    {
        "documents": "A2A Protocol Implementation:\nOpenJarvis implements the Google Agent-to-Agent spec using JSON-RPC 2.0. A2AServer supports tasks/send, tasks/get, and tasks/cancel operations. Agent discovery is available at /.well-known/agent.json. A2AClient enables calling external A2A agents. A2AAgentTool adapts A2A agents as tool-callable resources.",
        "question": "What protocol does A2A use and how are agents discovered?",
        "answer": "A2A uses JSON-RPC 2.0. Agents are discovered via /.well-known/agent.json.",
    },
    {
        "documents": "Deployment Guide:\nOpenJarvis provides three Docker variants: Dockerfile (Python 3.12-slim for CPU), Dockerfile.gpu (NVIDIA CUDA 12.4), and Dockerfile.gpu.rocm (AMD ROCm 6.2). The docker-compose.yml runs two services: jarvis on port 8000 and ollama on port 11434. SystemD and launchd service files are also provided for system-level deployment.",
        "question": "What Docker variants are available and what ports do the services use?",
        "answer": "Three Docker variants: CPU (Python 3.12-slim), NVIDIA (CUDA 12.4), and AMD (ROCm 6.2). Jarvis runs on port 8000 and Ollama on port 11434.",
    },
    {
        "documents": "Event System Reference:\nThe EventBus provides synchronous pub/sub event dispatch. Approximately 30 EventType values cover inference, tools, memory, agents, telemetry, traces, channels, security, scheduler, workflow, skills, sessions, and A2A. Subscribers register handlers for specific event types. Events are dispatched synchronously within the publishing thread.",
        "question": "How many EventType values does the system define and how are events dispatched?",
        "answer": "The system defines approximately 30 EventType values. Events are dispatched synchronously within the publishing thread.",
    },
    {
        "documents": "Cost Savings Analysis (Q4 2025):\nBy running inference locally using Ollama with quantized models, the team eliminated all API costs. Previous cloud spending: $8,120/month on GPT-4 API calls for email triage (every 5 min), research queries (20/day), and monitoring (continuous). After migration to local inference: $0/month in API fees, plus approximately $15/month in electricity costs for a consumer GPU running 24/7.",
        "question": "What was the monthly cloud spending before migration and what are the costs after?",
        "answer": "Cloud spending was $8,120/month. After migration to local inference: $0/month in API fees plus approximately $15/month in electricity for a consumer GPU.",
    },
    {
        "documents": "Hardware Detection System:\nOpenJarvis auto-detects GPU vendor, model, and VRAM using platform-specific tools: nvidia-smi for NVIDIA GPUs, rocm-smi for AMD GPUs, system_profiler for Apple Silicon, and /proc/cpuinfo for CPU features. Based on detection, it recommends the appropriate inference engine (vLLM for NVIDIA, MLX for Apple, llama.cpp for CPU-only).",
        "question": "How does OpenJarvis detect hardware and what engine is recommended for Apple Silicon?",
        "answer": "OpenJarvis detects hardware using nvidia-smi, rocm-smi, system_profiler, and /proc/cpuinfo. MLX is recommended for Apple Silicon.",
    },
    {
        "documents": "Template System Documentation:\nAgent templates are pre-configured TOML manifests with system prompts, tool sets, and behavioral parameters. 15 built-in templates exist including code-reviewer, debugger, architect, deep-researcher, fact-checker, and summarizer. Templates are loaded via load_template() and discovered via discover_templates(). Each template specifies the agent type, tools, and generation parameters.",
        "question": "How many built-in agent templates exist and name at least four of them.",
        "answer": "There are 15 built-in templates. Examples include code-reviewer, debugger, architect, deep-researcher, fact-checker, and summarizer.",
    },
    {
        "documents": "Scheduler System Guide:\nTaskScheduler supports three scheduling types: cron (cron expressions), interval (fixed time intervals), and once (one-time execution). Tasks are persisted to SQLite. Five MCP tools are available for task management. The scheduler integrates with the EventBus for notifications. CLI commands: create, list, pause, resume, cancel, logs, and start.",
        "question": "What scheduling types does TaskScheduler support?",
        "answer": "TaskScheduler supports three scheduling types: cron (cron expressions), interval (fixed time intervals), and once (one-time execution).",
    },
    {
        "documents": "TUI Dashboard Reference:\nThe terminal-based dashboard uses the textual library and is available with the [dashboard] optional dependency. It provides panels for system status, event stream, telemetry visualization, agent activity monitoring, and session management. The dashboard runs in the terminal and provides a real-time view of system operations.",
        "question": "What library powers the TUI dashboard and what panels does it include?",
        "answer": "The TUI dashboard is powered by the textual library. It includes panels for system status, event stream, telemetry, agent activity, and sessions.",
    },
    {
        "documents": "MCP Quick-Add Feature:\nThe 'jarvis add' command provides quick MCP server setup with 8 built-in templates: github, filesystem, slack, postgres, brave-search, memory, puppeteer, and google-maps. Configuration is saved as JSON to ~/.openjarvis/mcp/. Each template includes the server command, arguments, and required environment variables.",
        "question": "How many MCP server templates are available via 'jarvis add' and where is configuration saved?",
        "answer": "8 MCP server templates are available. Configuration is saved to ~/.openjarvis/mcp/.",
    },
    {
        "documents": "Composition Layer Documentation:\nSystemBuilder provides a fluent builder pattern that produces JarvisSystem instances. The builder wires together engine, model, agent, tools, telemetry, traces, workflow, sessions, and capability policy. JarvisSystem exposes ask() for queries and close() for resource cleanup. The SDK (Jarvis class) wraps SystemBuilder with a simplified sync API.",
        "question": "What is the relationship between SystemBuilder, JarvisSystem, and the Jarvis SDK class?",
        "answer": "SystemBuilder is a fluent builder that produces JarvisSystem instances. The Jarvis SDK class wraps SystemBuilder with a simplified synchronous API.",
    },
]


class KnowledgeBaseDataset(DatasetProvider):
    """Knowledge base benchmark: document-grounded retrieval and QA."""

    dataset_id = "knowledge_base"
    dataset_name = "Knowledge Base"

    def __init__(self) -> None:
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        rows = list(_RECORDS)

        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        self._records = []
        for idx, rec in enumerate(rows):
            prompt = _PROMPT_TEMPLATE.format(
                documents=rec["documents"],
                question=rec["question"],
            )
            self._records.append(
                EvalRecord(
                    record_id=f"knowledge-base-{idx}",
                    problem=prompt,
                    reference=rec["answer"],
                    category="use-case",
                    subject="knowledge_base",
                    metadata={},
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["KnowledgeBaseDataset"]

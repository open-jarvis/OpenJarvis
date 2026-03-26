"""Configuration loading, hardware detection, and engine recommendation.

User configuration lives at ``~/.openjarvis/config.toml``.  ``load_config()``
detects hardware, fills sensible defaults, then overlays any user overrides
found in the TOML file.
"""

from __future__ import annotations

import functools
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Hardware dataclasses
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_DIR = Path.home() / ".openjarvis"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"


@dataclass(slots=True)
class GpuInfo:
    """Detected GPU metadata."""

    vendor: str = ""
    name: str = ""
    vram_gb: float = 0.0
    compute_capability: str = ""
    count: int = 0


@dataclass(slots=True)
class HardwareInfo:
    """Detected system hardware."""

    platform: str = ""
    cpu_brand: str = ""
    cpu_count: int = 0
    ram_gb: float = 0.0
    gpu: Optional[GpuInfo] = None


# ---------------------------------------------------------------------------
# Hardware detection helpers
# ---------------------------------------------------------------------------


def _run_cmd(cmd: list[str]) -> str:
    """Run a command and return stripped stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,  # noqa: S603
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _detect_nvidia_gpu() -> Optional[GpuInfo]:
    if not shutil.which("nvidia-smi"):
        return None
    raw = _run_cmd(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,count",
            "--format=csv,noheader,nounits",
        ]
    )
    if not raw:
        return None
    try:
        first_line = raw.splitlines()[0]
        parts = [p.strip() for p in first_line.split(",")]
        name = parts[0]
        vram_mb = float(parts[1])
        count = int(parts[2])
        return GpuInfo(
            vendor="nvidia",
            name=name,
            vram_gb=round(vram_mb / 1024, 1),
            count=count,
        )
    except (IndexError, ValueError):
        return None


def _detect_amd_gpu() -> Optional[GpuInfo]:
    if not shutil.which("rocm-smi"):
        return None
    raw = _run_cmd(["rocm-smi", "--showproductname"])
    if not raw:
        return None
    name = raw.splitlines()[0] if raw else "AMD GPU"

    # Parse VRAM from rocm-smi --showmeminfo vram
    vram_gb = 0.0
    try:
        vram_raw = _run_cmd(["rocm-smi", "--showmeminfo", "vram"])
        for line in vram_raw.splitlines():
            if "Total Memory (B):" in line:
                vram_bytes = int(line.split(":")[-1].strip())
                vram_gb = round(vram_bytes / (1024**3), 1)
                break
    except (ValueError, IndexError):
        vram_gb = 0.0

    # Parse GPU count from rocm-smi --showallinfo
    count = 1
    try:
        allinfo_raw = _run_cmd(["rocm-smi", "--showallinfo"])
        import re

        gpu_ids = set(re.findall(r"GPU\[(\d+)\]", allinfo_raw))
        if gpu_ids:
            count = len(gpu_ids)
    except (ValueError, IndexError):
        count = 1

    return GpuInfo(vendor="amd", name=name, vram_gb=vram_gb, count=count)


def _detect_apple_gpu() -> Optional[GpuInfo]:
    if platform.system() != "Darwin":
        return None
    raw = _run_cmd(["system_profiler", "SPDisplaysDataType"])
    if "Apple" not in raw:
        return None
    # Rough extraction — "Apple M2 Max" etc.
    ram_gb = _total_ram_gb()
    for line in raw.splitlines():
        line = line.strip()
        if "Chipset Model" in line:
            name = line.split(":")[-1].strip()
            return GpuInfo(vendor="apple", name=name, vram_gb=ram_gb, count=1)
    return GpuInfo(vendor="apple", name="Apple Silicon", vram_gb=ram_gb, count=1)


def _detect_cpu_brand() -> str:
    """Best-effort CPU brand string."""
    if platform.system() == "Darwin":
        brand = _run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"])
        if brand:
            return brand
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        try:
            for line in cpuinfo.read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or "unknown"


def _total_ram_gb() -> float:
    try:
        if platform.system() == "Darwin":
            raw = _run_cmd(["sysctl", "-n", "hw.memsize"])
            return round(int(raw) / (1024**3), 1) if raw else 0.0
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemTotal"):
                    kb = int(line.split()[1])
                    return round(kb / (1024**2), 1)
    except (OSError, ValueError):
        pass
    return 0.0


def detect_hardware() -> HardwareInfo:
    """Auto-detect hardware capabilities with graceful fallbacks."""
    gpu = _detect_nvidia_gpu() or _detect_amd_gpu() or _detect_apple_gpu()
    return HardwareInfo(
        platform=platform.system().lower(),
        cpu_brand=_detect_cpu_brand(),
        cpu_count=os.cpu_count() or 1,
        ram_gb=_total_ram_gb(),
        gpu=gpu,
    )


# ---------------------------------------------------------------------------
# Engine recommendation
# ---------------------------------------------------------------------------


def recommend_engine(hw: HardwareInfo) -> str:
    """Suggest the best inference engine for the detected hardware."""
    gpu = hw.gpu
    if gpu is None:
        return "llamacpp"
    if gpu.vendor == "apple":
        return "mlx"
    if gpu.vendor == "nvidia":
        # Datacenter cards (A100, H100, L40, etc.) → vllm; consumer → ollama
        datacenter_keywords = ("A100", "H100", "H200", "L40", "A10", "A30")
        if any(kw in gpu.name for kw in datacenter_keywords):
            return "vllm"
        return "ollama"
    if gpu.vendor == "amd":
        return "vllm"
    return "llamacpp"


def recommend_model(hw: HardwareInfo, engine: str) -> str:
    """Suggest the largest Qwen3.5 model that fits the detected hardware.

    Uses llmfit-style VRAM estimation: Q4_K_M quantization is ~0.5 bytes/param
    with 10% overhead.  For MoE models Ollama loads full model weights, so we
    use ``parameter_count_b`` (total), not ``active_parameter_count_b``.
    """
    from openjarvis.intelligence.model_catalog import BUILTIN_MODELS

    # Determine available memory in GB
    gpu = hw.gpu
    if gpu and gpu.vram_gb > 0:
        available_gb = gpu.vram_gb * max(gpu.count, 1) * 0.9
    elif hw.ram_gb > 0:
        available_gb = (hw.ram_gb - 4) * 0.8
    else:
        return ""

    # Filter Qwen3.5 models compatible with the chosen engine
    candidates = [
        spec
        for spec in BUILTIN_MODELS
        if spec.provider == "alibaba"
        and spec.model_id.startswith("qwen3.5:")
        and engine in spec.supported_engines
    ]

    # Sort by parameter count descending — pick the largest that fits
    candidates.sort(key=lambda s: s.parameter_count_b, reverse=True)

    for spec in candidates:
        estimated_gb = spec.parameter_count_b * 0.5 * 1.1
        if estimated_gb <= available_gb:
            return spec.model_id

    return ""


def estimated_download_gb(parameter_count_b: float) -> float:
    """Estimate download size in GB for Q4_K_M quantized model."""
    return parameter_count_b * 0.5 * 1.1


# ---------------------------------------------------------------------------
# Configuration hierarchy
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OllamaEngineConfig:
    """Per-engine config for Ollama."""

    host: str = ""


@dataclass(slots=True)
class VLLMEngineConfig:
    """Per-engine config for vLLM."""

    host: str = "http://localhost:8000"


@dataclass(slots=True)
class SGLangEngineConfig:
    """Per-engine config for SGLang."""

    host: str = "http://localhost:30000"


@dataclass(slots=True)
class LlamaCppEngineConfig:
    """Per-engine config for llama.cpp."""

    host: str = "http://localhost:8080"
    binary_path: str = ""


@dataclass(slots=True)
class MLXEngineConfig:
    """Per-engine config for MLX."""

    host: str = "http://localhost:8080"


@dataclass(slots=True)
class LMStudioEngineConfig:
    """Per-engine config for LM Studio."""

    host: str = "http://localhost:1234"


@dataclass(slots=True)
class ExoEngineConfig:
    """Per-engine config for Exo."""

    host: str = "http://localhost:52415"


@dataclass(slots=True)
class NexaEngineConfig:
    """Per-engine config for Nexa."""

    host: str = "http://localhost:18181"
    device: str = ""


@dataclass(slots=True)
class UzuEngineConfig:
    """Per-engine config for Uzu."""

    host: str = "http://localhost:8000"


@dataclass(slots=True)
class AppleFmEngineConfig:
    """Per-engine config for Apple Foundation Models."""

    host: str = "http://localhost:8079"


@dataclass(slots=True)
class GemmaCppEngineConfig:
    """Per-engine config for gemma.cpp."""

    model_path: str = ""
    tokenizer_path: str = ""
    model_type: str = ""
    num_threads: int = 0


@dataclass
class EngineConfig:
    """Inference engine settings with nested per-engine configs."""

    default: str = "ollama"
    ollama: OllamaEngineConfig = field(default_factory=OllamaEngineConfig)
    vllm: VLLMEngineConfig = field(default_factory=VLLMEngineConfig)
    sglang: SGLangEngineConfig = field(default_factory=SGLangEngineConfig)
    llamacpp: LlamaCppEngineConfig = field(default_factory=LlamaCppEngineConfig)
    mlx: MLXEngineConfig = field(default_factory=MLXEngineConfig)
    lmstudio: LMStudioEngineConfig = field(default_factory=LMStudioEngineConfig)
    exo: ExoEngineConfig = field(default_factory=ExoEngineConfig)
    nexa: NexaEngineConfig = field(default_factory=NexaEngineConfig)
    uzu: UzuEngineConfig = field(default_factory=UzuEngineConfig)
    apple_fm: AppleFmEngineConfig = field(default_factory=AppleFmEngineConfig)
    gemma_cpp: GemmaCppEngineConfig = field(default_factory=GemmaCppEngineConfig)

    # Backward-compat properties for old flat attribute names
    @property
    def ollama_host(self) -> str:
        """Deprecated: use ``engine.ollama.host``."""
        return self.ollama.host

    @ollama_host.setter
    def ollama_host(self, value: str) -> None:
        self.ollama.host = value

    @property
    def vllm_host(self) -> str:
        """Deprecated: use ``engine.vllm.host``."""
        return self.vllm.host

    @vllm_host.setter
    def vllm_host(self, value: str) -> None:
        self.vllm.host = value

    @property
    def llamacpp_host(self) -> str:
        """Deprecated: use ``engine.llamacpp.host``."""
        return self.llamacpp.host

    @llamacpp_host.setter
    def llamacpp_host(self, value: str) -> None:
        self.llamacpp.host = value

    @property
    def llamacpp_path(self) -> str:
        """Deprecated: use ``engine.llamacpp.binary_path``."""
        return self.llamacpp.binary_path

    @llamacpp_path.setter
    def llamacpp_path(self, value: str) -> None:
        self.llamacpp.binary_path = value

    @property
    def sglang_host(self) -> str:
        """Deprecated: use ``engine.sglang.host``."""
        return self.sglang.host

    @sglang_host.setter
    def sglang_host(self, value: str) -> None:
        self.sglang.host = value

    @property
    def mlx_host(self) -> str:
        """Deprecated: use ``engine.mlx.host``."""
        return self.mlx.host

    @mlx_host.setter
    def mlx_host(self, value: str) -> None:
        self.mlx.host = value

    @property
    def lmstudio_host(self) -> str:
        """Deprecated: use ``engine.lmstudio.host``."""
        return self.lmstudio.host

    @lmstudio_host.setter
    def lmstudio_host(self, value: str) -> None:
        self.lmstudio.host = value

    @property
    def exo_host(self) -> str:
        """Deprecated: use ``engine.exo.host``."""
        return self.exo.host

    @exo_host.setter
    def exo_host(self, value: str) -> None:
        self.exo.host = value

    @property
    def nexa_host(self) -> str:
        """Deprecated: use ``engine.nexa.host``."""
        return self.nexa.host

    @nexa_host.setter
    def nexa_host(self, value: str) -> None:
        self.nexa.host = value

    @property
    def uzu_host(self) -> str:
        """Deprecated: use ``engine.uzu.host``."""
        return self.uzu.host

    @uzu_host.setter
    def uzu_host(self, value: str) -> None:
        self.uzu.host = value

    @property
    def apple_fm_host(self) -> str:
        """Deprecated: use ``engine.apple_fm.host``."""
        return self.apple_fm.host

    @apple_fm_host.setter
    def apple_fm_host(self, value: str) -> None:
        self.apple_fm.host = value


@dataclass(slots=True)
class IntelligenceConfig:
    """The model — identity, paths, quantization, and generation defaults."""

    default_model: str = ""
    fallback_model: str = ""
    model_path: str = ""  # Local weights (HF repo, GGUF file, etc.)
    checkpoint_path: str = ""  # Checkpoint/adapter path
    quantization: str = "none"  # none, fp8, int8, int4, gguf_q4, gguf_q8
    preferred_engine: str = ""  # Override engine for this model (e.g., "vllm")
    provider: str = ""  # local, openai, anthropic, google
    # Generation defaults (overridable per-call)
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 0.9
    top_k: int = 40
    repetition_penalty: float = 1.0
    stop_sequences: str = ""  # Comma-separated stop strings


@dataclass(slots=True)
class RoutingLearningConfig:
    """Routing sub-policy config within Learning."""

    policy: str = "heuristic"  # heuristic | learned
    min_samples: int = 5  # Min traces before trusting learned routing


@dataclass(slots=True)
class SFTConfig:
    """General-purpose SFT training config. Maps to [learning.intelligence.sft]."""

    model_name: str = "Qwen/Qwen3-1.7B"
    max_seq_length: int = 4096
    num_epochs: int = 3
    batch_size: int = 8
    learning_rate: float = 2e-5
    weight_decay: float = 0.01
    warmup_ratio: float = 0.1
    max_grad_norm: float = 1.0
    gradient_checkpointing: bool = True
    use_lora: bool = True
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: str = "q_proj,v_proj"  # comma-separated for TOML compat
    use_4bit: bool = False
    checkpoint_dir: str = "checkpoints/sft"
    min_pairs: int = 10
    agent_filter: str = ""


@dataclass(slots=True)
class GRPOConfig:
    """General-purpose GRPO training config. Maps to [learning.intelligence.grpo]."""

    model_name: str = "Qwen/Qwen3-1.7B"
    max_seq_length: int = 4096
    max_response_length: int = 2048
    num_epochs: int = 10
    batch_size: int = 16
    learning_rate: float = 1e-6
    max_grad_norm: float = 1.0
    gradient_checkpointing: bool = True
    num_samples_per_prompt: int = 8
    temperature: float = 1.0
    kl_coef: float = 0.0001
    clip_ratio: float = 0.2
    use_8bit_ref: bool = True
    checkpoint_dir: str = "checkpoints/grpo"
    save_every_n_epochs: int = 1
    keep_last_n: int = 3
    min_prompts: int = 10
    agent_filter: str = ""


@dataclass(slots=True)
class DSPyOptimizerConfig:
    """DSPy agent optimizer config. Maps to [learning.agent.dspy]."""

    optimizer: str = "BootstrapFewShotWithRandomSearch"
    task_lm: str = ""
    teacher_lm: str = ""
    max_bootstrapped_demos: int = 4
    max_labeled_demos: int = 4
    num_candidate_programs: int = 10
    max_rounds: int = 1
    optimize_system_prompt: bool = True
    optimize_few_shot: bool = True
    optimize_tool_descriptions: bool = True
    min_traces: int = 20
    metric_threshold: float = 0.7
    agent_filter: str = ""
    config_dir: str = ""


@dataclass(slots=True)
class GEPAOptimizerConfig:
    """GEPA agent optimizer config. Maps to [learning.agent.gepa]."""

    reflection_lm: str = ""
    max_metric_calls: int = 150
    population_size: int = 10
    optimize_system_prompt: bool = True
    optimize_tools: bool = True
    optimize_max_turns: bool = True
    optimize_temperature: bool = True
    min_traces: int = 20
    assessment_batch_size: int = 10
    agent_filter: str = ""
    config_dir: str = ""


@dataclass(slots=True)
class IntelligenceLearningConfig:
    """Intelligence sub-policy config within Learning."""

    policy: str = "none"  # none | sft | grpo
    sft: SFTConfig = field(default_factory=SFTConfig)
    grpo: GRPOConfig = field(default_factory=GRPOConfig)


@dataclass(slots=True)
class AgentLearningConfig:
    """Agent sub-policy config within Learning."""

    policy: str = "none"  # none | dspy | gepa
    dspy: DSPyOptimizerConfig = field(default_factory=DSPyOptimizerConfig)
    gepa: GEPAOptimizerConfig = field(default_factory=GEPAOptimizerConfig)


@dataclass(slots=True)
class MetricsConfig:
    """Reward / optimization metric weights."""

    accuracy_weight: float = 0.6
    latency_weight: float = 0.2
    cost_weight: float = 0.1
    efficiency_weight: float = 0.1


@dataclass
class LearningConfig:
    """Learning system settings with per-primitive sub-policies."""

    enabled: bool = False
    update_interval: int = 100
    auto_update: bool = False
    routing: RoutingLearningConfig = field(default_factory=RoutingLearningConfig)
    intelligence: IntelligenceLearningConfig = field(
        default_factory=IntelligenceLearningConfig,
    )
    agent: AgentLearningConfig = field(default_factory=AgentLearningConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)

    # Training pipeline
    training_enabled: bool = False
    training_schedule: str = ""
    min_improvement: float = 0.02

    # Backward-compat properties for old flat field names
    @property
    def default_policy(self) -> str:
        """Deprecated: use ``learning.routing.policy``."""
        return self.routing.policy

    @default_policy.setter
    def default_policy(self, value: str) -> None:
        self.routing.policy = value

    @property
    def intelligence_policy(self) -> str:
        """Deprecated: use ``learning.intelligence.policy``."""
        return self.intelligence.policy

    @intelligence_policy.setter
    def intelligence_policy(self, value: str) -> None:
        self.intelligence.policy = value

    @property
    def agent_policy(self) -> str:
        """Deprecated: use ``learning.agent.policy``."""
        return self.agent.policy

    @agent_policy.setter
    def agent_policy(self, value: str) -> None:
        self.agent.policy = value

    @property
    def reward_weights(self) -> str:
        """Deprecated: use ``learning.metrics.*``."""
        parts = []
        m = self.metrics
        if m.latency_weight:
            parts.append(f"latency={m.latency_weight}")
        if m.cost_weight:
            parts.append(f"cost={m.cost_weight}")
        if m.efficiency_weight:
            parts.append(f"efficiency={m.efficiency_weight}")
        if m.accuracy_weight:
            parts.append(f"accuracy={m.accuracy_weight}")
        return ",".join(parts)

    @reward_weights.setter
    def reward_weights(self, value: str) -> None:
        if not value:
            return
        for part in value.split(","):
            if "=" not in part:
                continue
            key, val = part.strip().split("=", 1)
            key = key.strip()
            fval = float(val.strip())
            if key == "accuracy":
                self.metrics.accuracy_weight = fval
            elif key == "latency":
                self.metrics.latency_weight = fval
            elif key == "cost":
                self.metrics.cost_weight = fval
            elif key == "efficiency":
                self.metrics.efficiency_weight = fval


@dataclass(slots=True)
class StorageConfig:
    """Storage (memory) backend settings."""

    default_backend: str = "sqlite"
    db_path: str = str(DEFAULT_CONFIG_DIR / "memory.db")
    context_top_k: int = 5
    context_min_score: float = 0.1
    context_max_tokens: int = 2048
    chunk_size: int = 512
    chunk_overlap: int = 64


# Backward-compatibility alias
MemoryConfig = StorageConfig


@dataclass(slots=True)
class MCPConfig:
    """MCP (Model Context Protocol) settings."""

    enabled: bool = True
    servers: str = ""  # JSON list of MCP server configs


@dataclass(slots=True)
class BrowserConfig:
    """Browser automation settings (Playwright)."""

    headless: bool = True
    timeout_ms: int = 30000
    viewport_width: int = 1280
    viewport_height: int = 720


@dataclass(slots=True)
class ToolsConfig:
    """Tools primitive settings — wraps storage and MCP configuration."""

    storage: StorageConfig = field(default_factory=StorageConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    enabled: str = ""  # comma-separated default tools


@dataclass
class AgentConfig:
    """Agent harness settings — orchestration, tools, system prompt."""

    default_agent: str = "simple"
    max_turns: int = 10
    tools: str = ""  # comma-separated tool names
    objective: str = ""  # concise purpose for routing/learning/docs
    system_prompt: str = ""  # inline system prompt (takes precedence if set)
    system_prompt_path: str = ""  # path to system prompt file (.txt, .md)
    context_from_memory: bool = True  # inject relevant memory context into prompts

    # Backward-compat property for old field name
    @property
    def default_tools(self) -> str:
        """Deprecated: use ``agent.tools``."""
        return self.tools

    @default_tools.setter
    def default_tools(self, value: str) -> None:
        self.tools = value


@dataclass(slots=True)
class ServerConfig:
    """API server settings."""

    host: str = "0.0.0.0"
    port: int = 8000
    agent: str = "orchestrator"
    model: str = ""
    workers: int = 1


@dataclass(slots=True)
class TelemetryConfig:
    """Telemetry persistence settings."""

    enabled: bool = True
    db_path: str = str(DEFAULT_CONFIG_DIR / "telemetry.db")
    gpu_metrics: bool = False
    gpu_poll_interval_ms: int = 50
    energy_vendor: str = ""  # auto-detect or force "nvidia"/"amd"/"apple"/"cpu_rapl"
    warmup_samples: int = 0
    steady_state_window: int = 5
    steady_state_threshold: float = 0.05


@dataclass(slots=True)
class TracesConfig:
    """Trace system settings."""

    enabled: bool = True
    db_path: str = str(DEFAULT_CONFIG_DIR / "traces.db")


@dataclass(slots=True)
class TelegramChannelConfig:
    """Per-channel config for Telegram."""

    bot_token: str = ""
    allowed_chat_ids: str = ""
    parse_mode: str = "Markdown"


@dataclass(slots=True)
class DiscordChannelConfig:
    """Per-channel config for Discord."""

    bot_token: str = ""


@dataclass(slots=True)
class SlackChannelConfig:
    """Per-channel config for Slack."""

    bot_token: str = ""
    app_token: str = ""


@dataclass(slots=True)
class WebhookChannelConfig:
    """Per-channel config for generic webhooks."""

    url: str = ""
    secret: str = ""
    method: str = "POST"


@dataclass(slots=True)
class EmailChannelConfig:
    """Per-channel config for email (SMTP/IMAP)."""

    smtp_host: str = ""
    smtp_port: int = 587
    imap_host: str = ""
    imap_port: int = 993
    username: str = ""
    password: str = ""
    use_tls: bool = True


@dataclass(slots=True)
class WhatsAppChannelConfig:
    """Per-channel config for WhatsApp Cloud API."""

    access_token: str = ""
    phone_number_id: str = ""


@dataclass(slots=True)
class SignalChannelConfig:
    """Per-channel config for Signal (via signal-cli REST API)."""

    api_url: str = ""
    phone_number: str = ""


@dataclass(slots=True)
class GoogleChatChannelConfig:
    """Per-channel config for Google Chat webhooks."""

    webhook_url: str = ""


@dataclass(slots=True)
class IRCChannelConfig:
    """Per-channel config for IRC."""

    server: str = ""
    port: int = 6667
    nick: str = ""
    password: str = ""
    use_tls: bool = False


@dataclass(slots=True)
class WebChatChannelConfig:
    """Per-channel config for in-memory webchat."""

    pass


@dataclass(slots=True)
class TeamsChannelConfig:
    """Per-channel config for Microsoft Teams (Bot Framework)."""

    app_id: str = ""
    app_password: str = ""
    service_url: str = ""


@dataclass(slots=True)
class MatrixChannelConfig:
    """Per-channel config for Matrix."""

    homeserver: str = ""
    access_token: str = ""


@dataclass(slots=True)
class MattermostChannelConfig:
    """Per-channel config for Mattermost."""

    url: str = ""
    token: str = ""


@dataclass(slots=True)
class FeishuChannelConfig:
    """Per-channel config for Feishu (Lark)."""

    app_id: str = ""
    app_secret: str = ""


@dataclass(slots=True)
class BlueBubblesChannelConfig:
    """Per-channel config for BlueBubbles (iMessage bridge)."""

    url: str = ""
    password: str = ""


@dataclass(slots=True)
class WhatsAppBaileysChannelConfig:
    """Per-channel config for WhatsApp via Baileys protocol."""

    auth_dir: str = ""  # Defaults to ~/.openjarvis/whatsapp_auth
    assistant_name: str = "Jarvis"
    assistant_has_own_number: bool = False


@dataclass
class ChannelConfig:
    """Channel messaging settings."""

    enabled: bool = False
    default_channel: str = ""
    default_agent: str = "simple"
    telegram: TelegramChannelConfig = field(default_factory=TelegramChannelConfig)
    discord: DiscordChannelConfig = field(default_factory=DiscordChannelConfig)
    slack: SlackChannelConfig = field(default_factory=SlackChannelConfig)
    webhook: WebhookChannelConfig = field(default_factory=WebhookChannelConfig)
    email: EmailChannelConfig = field(default_factory=EmailChannelConfig)
    whatsapp: WhatsAppChannelConfig = field(default_factory=WhatsAppChannelConfig)
    signal: SignalChannelConfig = field(default_factory=SignalChannelConfig)
    google_chat: GoogleChatChannelConfig = field(
        default_factory=GoogleChatChannelConfig,
    )
    irc: IRCChannelConfig = field(default_factory=IRCChannelConfig)
    webchat: WebChatChannelConfig = field(default_factory=WebChatChannelConfig)
    teams: TeamsChannelConfig = field(default_factory=TeamsChannelConfig)
    matrix: MatrixChannelConfig = field(default_factory=MatrixChannelConfig)
    mattermost: MattermostChannelConfig = field(default_factory=MattermostChannelConfig)
    feishu: FeishuChannelConfig = field(default_factory=FeishuChannelConfig)
    bluebubbles: BlueBubblesChannelConfig = field(
        default_factory=BlueBubblesChannelConfig,
    )
    whatsapp_baileys: WhatsAppBaileysChannelConfig = field(
        default_factory=WhatsAppBaileysChannelConfig,
    )


@dataclass(slots=True)
class CapabilitiesConfig:
    """RBAC capability system settings."""

    enabled: bool = False
    policy_path: str = ""


@dataclass(slots=True)
class SecurityConfig:
    """Security guardrails settings."""

    enabled: bool = True
    scan_input: bool = True
    scan_output: bool = True
    mode: str = "warn"  # "redact" | "warn" | "block"
    secret_scanner: bool = True
    pii_scanner: bool = True
    audit_log_path: str = str(DEFAULT_CONFIG_DIR / "audit.db")
    enforce_tool_confirmation: bool = True
    merkle_audit: bool = True
    signing_key_path: str = ""
    ssrf_protection: bool = True
    rate_limit_enabled: bool = False
    rate_limit_rpm: int = 60
    rate_limit_burst: int = 10
    capabilities: CapabilitiesConfig = field(default_factory=CapabilitiesConfig)


@dataclass(slots=True)
class SandboxConfig:
    """Container sandbox settings."""

    enabled: bool = False
    image: str = "openjarvis-sandbox:latest"
    timeout: int = 300
    workspace: str = ""
    mount_allowlist_path: str = ""
    max_concurrent: int = 5
    runtime: str = "docker"
    wasm_fuel_limit: int = 1_000_000
    wasm_memory_limit_mb: int = 256


@dataclass(slots=True)
class SchedulerConfig:
    """Task scheduler settings."""

    enabled: bool = False
    poll_interval: int = 60
    db_path: str = ""  # Defaults to ~/.openjarvis/scheduler.db


@dataclass(slots=True)
class WorkflowConfig:
    """Workflow engine settings."""

    enabled: bool = False
    max_parallel: int = 4
    default_node_timeout: int = 300


@dataclass(slots=True)
class SessionConfig:
    """Cross-channel session settings."""

    enabled: bool = False
    max_age_hours: float = 24.0
    consolidation_threshold: int = 100
    db_path: str = str(DEFAULT_CONFIG_DIR / "sessions.db")


@dataclass(slots=True)
class A2AConfig:
    """Agent-to-Agent protocol settings."""

    enabled: bool = False


@dataclass(slots=True)
class OperatorsConfig:
    """Operator lifecycle settings."""

    enabled: bool = False
    manifests_dir: str = "~/.openjarvis/operators"
    auto_activate: str = ""  # Comma-separated operator IDs


@dataclass(slots=True)
class SpeechConfig:
    """Speech-to-text settings."""

    backend: str = "auto"  # "auto", "faster-whisper", "openai", "deepgram"
    model: str = "base"  # Whisper model size: tiny, base, small, medium, large-v3
    language: str = ""  # Empty = auto-detect
    device: str = "auto"  # "auto", "cpu", "cuda"
    compute_type: str = "float16"  # "float16", "int8", "float32"


@dataclass(slots=True)
class OptimizeConfig:
    """Configuration optimization settings."""

    max_trials: int = 20
    early_stop_patience: int = 5
    optimizer_model: str = "claude-sonnet-4-6"
    optimizer_provider: str = "anthropic"
    benchmark: str = ""
    max_samples: int = 50
    judge_model: str = "gpt-5-mini-2025-08-07"
    db_path: str = str(DEFAULT_CONFIG_DIR / "optimize.db")


@dataclass(slots=True)
class AgentManagerConfig:
    """Persistent agent manager settings."""

    enabled: bool = True
    db_path: str = str(DEFAULT_CONFIG_DIR / "agents.db")


@dataclass(slots=True)
class MemoryFilesConfig:
    """Persistent memory-file paths and nudge settings."""

    soul_path: str = "~/.openjarvis/SOUL.md"
    memory_path: str = "~/.openjarvis/MEMORY.md"
    user_path: str = "~/.openjarvis/USER.md"
    nudge_interval: int = 10


@dataclass(slots=True)
class SystemPromptConfig:
    """Limits and strategy for system-prompt assembly."""

    soul_max_chars: int = 4000
    memory_max_chars: int = 2500
    user_max_chars: int = 1500
    skill_desc_max_chars: int = 60
    truncation_strategy: str = "head_tail"


@dataclass(slots=True)
class CompressionConfig:
    """Configuration for context compression."""

    enabled: bool = True
    threshold: float = 0.50
    strategy: str = "session_consolidation"


@dataclass(slots=True)
class SkillsConfig:
    """Configuration for agent-authored procedural skills."""

    skills_dir: str = "~/.openjarvis/skills/"
    nudge_interval: int = 15
    auto_discover: bool = True


@dataclass
class JarvisConfig:
    """Top-level configuration for OpenJarvis."""

    hardware: HardwareInfo = field(default_factory=HardwareInfo)
    engine: EngineConfig = field(default_factory=EngineConfig)
    intelligence: IntelligenceConfig = field(default_factory=IntelligenceConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    traces: TracesConfig = field(default_factory=TracesConfig)
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    a2a: A2AConfig = field(default_factory=A2AConfig)
    operators: OperatorsConfig = field(default_factory=OperatorsConfig)
    speech: SpeechConfig = field(default_factory=SpeechConfig)
    optimize: OptimizeConfig = field(default_factory=OptimizeConfig)
    agent_manager: AgentManagerConfig = field(default_factory=AgentManagerConfig)
    memory_files: MemoryFilesConfig = field(default_factory=MemoryFilesConfig)
    system_prompt: SystemPromptConfig = field(default_factory=SystemPromptConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)

    @property
    def memory(self) -> StorageConfig:
        """Backward-compatible accessor — canonical location is tools.storage."""
        return self.tools.storage

    @memory.setter
    def memory(self, value: StorageConfig) -> None:
        """Backward-compatible setter."""
        self.tools.storage = value


# ---------------------------------------------------------------------------
# Config key validation
# ---------------------------------------------------------------------------

# Sections that users may set via ``jarvis config set``.
# ``hardware`` is auto-detected and not user-settable.
_SETTABLE_SECTIONS = frozenset(JarvisConfig.__dataclass_fields__.keys()) - {"hardware"}


def validate_config_key(dotted_key: str) -> type:
    """Validate a dotted config key and return the leaf field's Python type.

    Raises :class:`ValueError` when the key does not map to a known field.
    The function walks the ``JarvisConfig`` dataclass hierarchy using
    ``dataclasses.fields()``.

    Examples::

        validate_config_key("engine.ollama.host")      # -> str
        validate_config_key("intelligence.temperature") # -> float
    """
    from dataclasses import fields as dc_fields

    parts = dotted_key.split(".")
    if len(parts) < 2:
        raise ValueError(
            f"Config key must have at least two segments (e.g. engine.default), "
            f"got: {dotted_key!r}"
        )

    if parts[0] not in _SETTABLE_SECTIONS:
        raise ValueError(
            f"Unknown config key: {dotted_key!r} "
            f"(valid top-level sections: {sorted(_SETTABLE_SECTIONS)})"
        )

    # Walk the dataclass tree
    current_cls = JarvisConfig
    for i, part in enumerate(parts):
        field_map = {f.name: f for f in dc_fields(current_cls)}
        if part not in field_map:
            path_so_far = ".".join(parts[: i + 1])
            raise ValueError(
                f"Unknown config key: {dotted_key!r} "
                f"(no field {part!r} at {path_so_far}; "
                f"valid fields: {sorted(field_map.keys())})"
            )
        fld = field_map[part]
        # Resolve the type — unwrap Optional, etc.
        fld_type = fld.type
        if isinstance(fld_type, str):
            # Evaluate forward references in the config module namespace
            import openjarvis.core.config as _cfg_mod

            fld_type = eval(fld_type, vars(_cfg_mod))  # noqa: S307

        if i == len(parts) - 1:
            # Leaf — return the primitive type
            return fld_type
        else:
            # Must be a nested dataclass
            if not hasattr(fld_type, "__dataclass_fields__"):
                path_so_far = ".".join(parts[: i + 1])
                raise ValueError(
                    f"Unknown config key: {dotted_key!r} "
                    f"({path_so_far} is a leaf of type {fld_type.__name__}, "
                    f"not a section)"
                )
            current_cls = fld_type

    # Should not reach here, but satisfy type checker
    raise ValueError(f"Unknown config key: {dotted_key!r}")


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------


def _apply_toml_section(target: Any, section: Dict[str, Any]) -> None:
    """Overlay TOML key/value pairs onto a dataclass instance.

    Recursively handles nested dicts when the target attribute is itself
    a dataclass.  Normalises TOML arrays to comma-separated strings when
    the target field is annotated as ``str``.
    """
    for key, value in section.items():
        if hasattr(target, key):
            if isinstance(value, dict):
                nested = getattr(target, key)
                if hasattr(nested, "__dataclass_fields__"):
                    _apply_toml_section(nested, value)
                else:
                    setattr(target, key, value)
            else:
                # Normalise TOML arrays → comma-separated string when field is str
                if isinstance(value, list) and hasattr(target, "__dataclass_fields__"):
                    field_obj = target.__dataclass_fields__.get(key)
                    if field_obj is not None and field_obj.type in ("str", str):
                        value = ",".join(str(v) for v in value)
                setattr(target, key, value)


def _migrate_toml_data(data: Dict[str, Any], cfg: "JarvisConfig") -> None:
    """Migrate old-format TOML keys to new structure in-place.

    Handles cross-section moves that can't be solved by backward-compat
    properties alone (e.g. ``agent.temperature`` → ``intelligence.temperature``).
    """
    # agent.temperature / agent.max_tokens → intelligence.*
    if "agent" in data:
        agent_data = data["agent"]
        intel_data = data.setdefault("intelligence", {})
        for moved_key in ("temperature", "max_tokens"):
            if moved_key in agent_data:
                intel_data.setdefault(moved_key, agent_data.pop(moved_key))

    # context_injection from memory / tools.storage → agent.context_from_memory
    for src_section in ("memory",):
        src = data.get(src_section, {})
        if isinstance(src, dict) and "context_injection" in src:
            data.setdefault("agent", {}).setdefault(
                "context_from_memory",
                src.pop("context_injection"),
            )

    if "tools" in data:
        tools_data = data["tools"]
        if isinstance(tools_data, dict):
            storage_sub = tools_data.get("storage", {})
            if isinstance(storage_sub, dict) and "context_injection" in storage_sub:
                data.setdefault("agent", {}).setdefault(
                    "context_from_memory",
                    storage_sub.pop("context_injection"),
                )


@functools.lru_cache(maxsize=1)
def load_config(path: Optional[Path] = None) -> JarvisConfig:
    """Detect hardware, build defaults, overlay TOML overrides.

    Parameters
    ----------
    path:
        Explicit config file. If not set, uses ``OPENJARVIS_CONFIG`` when set,
        otherwise ``~/.openjarvis/config.toml``.
    """
    hw = detect_hardware()
    cfg = JarvisConfig(hardware=hw)
    cfg.engine.default = recommend_engine(hw)

    if path is not None:
        config_path = Path(path)
    elif os.environ.get("OPENJARVIS_CONFIG"):
        config_path = Path(os.environ["OPENJARVIS_CONFIG"]).expanduser().resolve()
    else:
        config_path = DEFAULT_CONFIG_PATH
    if config_path.exists():
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)

        # Run backward-compat migrations before applying
        _migrate_toml_data(data, cfg)

        # All top-level sections — recursive _apply_toml_section handles
        # nested sub-configs (engine.ollama, learning.routing, channel.*, etc.)
        top_sections = (
            "engine",
            "intelligence",
            "learning",
            "agent",
            "server",
            "telemetry",
            "traces",
            "security",
            "channel",
            "tools",
            "sandbox",
            "scheduler",
            "workflow",
            "sessions",
            "a2a",
            "operators",
            "speech",
            "optimize",
            "agent_manager",
        )
        for section_name in top_sections:
            if section_name in data:
                _apply_toml_section(
                    getattr(cfg, section_name),
                    data[section_name],
                )

        # Memory: accept [memory] (old) → maps to tools.storage
        if "memory" in data:
            _apply_toml_section(cfg.tools.storage, data["memory"])

    return cfg


# ---------------------------------------------------------------------------
# Default TOML generation (for ``jarvis init``)
# ---------------------------------------------------------------------------


def generate_minimal_toml(
    hw: HardwareInfo, engine: str | None = None, *, host: str | None = None
) -> str:
    """Render a minimal TOML config with only essential settings."""
    engine = engine or recommend_engine(hw)
    model = recommend_model(hw, engine)
    gpu_comment = ""
    if hw.gpu:
        mem_label = "unified memory" if hw.gpu.vendor == "apple" else "VRAM"
        gpu_comment = f"\n# GPU: {hw.gpu.name} ({hw.gpu.vram_gb} GB {mem_label})"
    if host:
        engine_host_section = f'\n[engine.{engine}]\nhost = "{host}"\n'
    else:
        engine_host_section = (
            f"\n[engine.{engine}]\n"
            f'# host = "http://localhost:11434"  '
            f"# set to remote URL if engine runs elsewhere\n"
        )
    return f"""\
# OpenJarvis configuration
# Hardware: {hw.cpu_brand} ({hw.cpu_count} cores, {hw.ram_gb} GB RAM){gpu_comment}
# Full reference config: jarvis init --full

[engine]
default = "{engine}"
{engine_host_section}
[intelligence]
default_model = "{model}"

[agent]
default_agent = "simple"

[tools]
enabled = ["code_interpreter", "web_search", "file_read", "shell_exec"]
"""


def generate_default_toml(
    hw: HardwareInfo, engine: str | None = None, *, host: str | None = None
) -> str:
    """Render a commented TOML string suitable for ``~/.openjarvis/config.toml``."""
    engine = engine or recommend_engine(hw)
    model = recommend_model(hw, engine)
    gpu_line = ""
    if hw.gpu:
        gpu_line = f"# Detected GPU: {hw.gpu.name} ({hw.gpu.vram_gb} GB VRAM)"

    model_comment = ""
    if model:
        model_comment = "  # recommended for your hardware"

    result = f"""\
# OpenJarvis configuration
# Generated by `jarvis init`
#
# Hardware: {hw.cpu_brand} ({hw.cpu_count} cores, {hw.ram_gb} GB RAM)
{gpu_line}

[engine]
default = "{engine}"

[engine.ollama]
host = "http://localhost:11434"

[engine.vllm]
host = "http://localhost:8000"

[engine.sglang]
host = "http://localhost:30000"

# [engine.llamacpp]
# host = "http://localhost:8080"
# binary_path = ""

[engine.mlx]
host = "http://localhost:8080"

# [engine.lmstudio]
# host = "http://localhost:1234"

# [engine.exo]
# host = "http://localhost:52415"

# [engine.nexa]
# host = "http://localhost:18181"
# device = ""  # cpu, gpu, npu

# [engine.uzu]
# host = "http://localhost:8080"

# [engine.apple_fm]
# host = "http://localhost:8079"

[intelligence]
default_model = "{model}"{model_comment}
fallback_model = ""
# model_path = ""              # Local weights (HF repo, GGUF file, etc.)
# checkpoint_path = ""         # Checkpoint/adapter path
# quantization = "none"        # none, fp8, int8, int4, gguf_q4, gguf_q8
# preferred_engine = ""        # Override engine for this model (e.g., "vllm")
# provider = ""                # local, openai, anthropic, google
temperature = 0.7
max_tokens = 1024
# top_p = 0.9
# top_k = 40
# repetition_penalty = 1.0
# stop_sequences = ""

[agent]
default_agent = "simple"
max_turns = 10
# tools = ""                   # Comma-separated tool names
# objective = ""               # Concise purpose string
# system_prompt = ""           # Inline system prompt
# system_prompt_path = ""      # Path to system prompt file
context_from_memory = true

[tools.storage]
default_backend = "sqlite"

[tools.mcp]
enabled = true

# [tools.browser]
# headless = true
# timeout_ms = 30000
# viewport_width = 1280
# viewport_height = 720

[server]
host = "0.0.0.0"
port = 8000
agent = "orchestrator"

[learning]
enabled = false
update_interval = 100
# auto_update = false

[learning.routing]
policy = "heuristic"
# min_samples = 5

# [learning.intelligence]
# policy = "none"              # "sft" to learn from traces

# [learning.agent]
# policy = "none"              # "agent_advisor" | "icl_updater"

# [learning.metrics]
# accuracy_weight = 0.6
# latency_weight = 0.2
# cost_weight = 0.1
# efficiency_weight = 0.1

[telemetry]
enabled = true
# gpu_metrics = false
# gpu_poll_interval_ms = 50

[traces]
enabled = false

[channel]
enabled = false
default_agent = "simple"

# [channel.telegram]
# bot_token = ""  # Or set TELEGRAM_BOT_TOKEN env var

# [channel.discord]
# bot_token = ""  # Or set DISCORD_BOT_TOKEN env var

# [channel.slack]
# bot_token = ""  # Or set SLACK_BOT_TOKEN env var

# [channel.webhook]
# url = ""

# [channel.whatsapp]
# access_token = ""      # Or set WHATSAPP_ACCESS_TOKEN env var
# phone_number_id = ""   # Or set WHATSAPP_PHONE_NUMBER_ID env var

# [channel.signal]
# api_url = ""            # signal-cli REST API URL
# phone_number = ""       # Or set SIGNAL_PHONE_NUMBER env var

# [channel.google_chat]
# webhook_url = ""        # Or set GOOGLE_CHAT_WEBHOOK_URL env var

# [channel.irc]
# server = ""
# port = 6667
# nick = ""
# use_tls = false

# [channel.teams]
# app_id = ""             # Or set TEAMS_APP_ID env var
# app_password = ""       # Or set TEAMS_APP_PASSWORD env var

# [channel.matrix]
# homeserver = ""         # Or set MATRIX_HOMESERVER env var
# access_token = ""       # Or set MATRIX_ACCESS_TOKEN env var

# [channel.mattermost]
# url = ""                # Or set MATTERMOST_URL env var
# token = ""              # Or set MATTERMOST_TOKEN env var

# [channel.feishu]
# app_id = ""             # Or set FEISHU_APP_ID env var
# app_secret = ""         # Or set FEISHU_APP_SECRET env var

# [channel.bluebubbles]
# url = ""                # Or set BLUEBUBBLES_URL env var
# password = ""           # Or set BLUEBUBBLES_PASSWORD env var

[security]
enabled = true
mode = "warn"
scan_input = true
scan_output = true
secret_scanner = true
pii_scanner = true
enforce_tool_confirmation = true
ssrf_protection = true
# rate_limit_enabled = false
# rate_limit_rpm = 60
# rate_limit_burst = 10

# [sandbox]
# enabled = false
# image = "openjarvis-sandbox:latest"
# timeout = 300
# max_concurrent = 5
# runtime = "docker"

# [scheduler]
# enabled = false
# poll_interval = 60
# db_path = ""                # Defaults to ~/.openjarvis/scheduler.db

# [channel.whatsapp_baileys]
# auth_dir = ""               # Defaults to ~/.openjarvis/whatsapp_auth
# assistant_name = "Jarvis"
# assistant_has_own_number = false
"""
    if host:
        import re as _re

        pattern = _re.escape(f"[engine.{engine}]") + r"\nhost = \"[^\"]*\""
        replacement = f'[engine.{engine}]\\nhost = "{host}"'
        result = _re.sub(pattern, replacement, result)
    return result


__all__ = [
    "A2AConfig",
    "AgentConfig",
    "AgentManagerConfig",
    "OperatorsConfig",
    "AgentLearningConfig",
    "BlueBubblesChannelConfig",
    "BrowserConfig",
    "CapabilitiesConfig",
    "ChannelConfig",
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_CONFIG_PATH",
    "DiscordChannelConfig",
    "EmailChannelConfig",
    "EngineConfig",
    "FeishuChannelConfig",
    "GoogleChatChannelConfig",
    "GpuInfo",
    "HardwareInfo",
    "IRCChannelConfig",
    "IntelligenceConfig",
    "IntelligenceLearningConfig",
    "JarvisConfig",
    "LearningConfig",
    "LMStudioEngineConfig",
    "LlamaCppEngineConfig",
    "MCPConfig",
    "MLXEngineConfig",
    "MatrixChannelConfig",
    "MattermostChannelConfig",
    "MemoryConfig",
    "MetricsConfig",
    "OllamaEngineConfig",
    "OptimizeConfig",
    "RoutingLearningConfig",
    "SGLangEngineConfig",
    "SandboxConfig",
    "SchedulerConfig",
    "SecurityConfig",
    "ServerConfig",
    "SessionConfig",
    "SignalChannelConfig",
    "SlackChannelConfig",
    "SpeechConfig",
    "StorageConfig",
    "TeamsChannelConfig",
    "TelegramChannelConfig",
    "TelemetryConfig",
    "ToolsConfig",
    "TracesConfig",
    "VLLMEngineConfig",
    "WebChatChannelConfig",
    "WebhookChannelConfig",
    "WhatsAppBaileysChannelConfig",
    "WhatsAppChannelConfig",
    "WorkflowConfig",
    "detect_hardware",
    "generate_default_toml",
    "generate_minimal_toml",
    "load_config",
    "recommend_engine",
    "recommend_model",
    "validate_config_key",
]

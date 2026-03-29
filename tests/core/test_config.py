"""Tests for configuration, hardware detection, and engine recommendation."""

from __future__ import annotations

from pathlib import Path

from openjarvis.core.config import (
    AgentConfig,
    ChannelConfig,
    EngineConfig,
    GpuInfo,
    HardwareInfo,
    IntelligenceConfig,
    JarvisConfig,
    LearningConfig,
    SandboxConfig,
    SchedulerConfig,
    SecurityConfig,
    WhatsAppBaileysChannelConfig,
    generate_default_toml,
    load_config,
    recommend_engine,
)


class TestDefaults:
    def test_jarvis_config_defaults(self) -> None:
        cfg = JarvisConfig()
        assert cfg.engine.default == "ollama"
        assert cfg.memory.default_backend == "sqlite"
        assert cfg.telemetry.enabled is True

    def test_engine_config_defaults(self) -> None:
        ec = EngineConfig()
        # Nested configs
        assert ec.ollama.host == ""
        assert ec.vllm.host == "http://localhost:8000"
        assert ec.sglang.host == "http://localhost:30000"
        assert ec.llamacpp.host == "http://localhost:8080"
        assert ec.llamacpp.binary_path == ""
        # Backward-compat properties still work
        assert ec.ollama_host == ""
        assert ec.vllm_host == "http://localhost:8000"


class TestRecommendEngine:
    def test_no_gpu(self) -> None:
        hw = HardwareInfo(platform="linux")
        assert recommend_engine(hw) == "llamacpp"

    def test_apple_silicon(self) -> None:
        hw = HardwareInfo(
            platform="darwin",
            gpu=GpuInfo(vendor="apple", name="Apple M2 Max"),
        )
        assert recommend_engine(hw) == "mlx"

    def test_nvidia_datacenter(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            gpu=GpuInfo(vendor="nvidia", name="NVIDIA A100-SXM4-80GB", vram_gb=80),
        )
        assert recommend_engine(hw) == "vllm"

    def test_nvidia_consumer(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            gpu=GpuInfo(vendor="nvidia", name="NVIDIA GeForce RTX 4090", vram_gb=24),
        )
        assert recommend_engine(hw) == "ollama"

    def test_amd(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            gpu=GpuInfo(vendor="amd", name="Radeon RX 7900 XTX"),
        )
        assert recommend_engine(hw) == "vllm"


class TestTomlLoading:
    def test_load_missing_file_uses_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert isinstance(cfg, JarvisConfig)
        # engine default is derived from detected hardware — just ensure it's a string
        assert isinstance(cfg.engine.default, str)

    def test_load_overrides(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[engine]\ndefault = "vllm"\n\n[memory]\ndefault_backend = "faiss"\n'
        )
        cfg = load_config(toml_file)
        assert cfg.engine.default == "vllm"
        assert cfg.memory.default_backend == "faiss"


class TestGenerateToml:
    def test_contains_engine_section(self) -> None:
        hw = HardwareInfo(
            platform="linux",
            cpu_brand="Intel Xeon",
            cpu_count=16,
            ram_gb=64.0,
            gpu=GpuInfo(vendor="nvidia", name="NVIDIA H100", vram_gb=80),
        )
        toml = generate_default_toml(hw)
        assert "[engine]" in toml
        assert 'default = "vllm"' in toml
        assert "H100" in toml


class TestSecurityConfig:
    def test_security_config_defaults(self) -> None:
        sc = SecurityConfig()
        assert sc.enabled is True
        assert sc.scan_input is True
        assert sc.scan_output is True
        assert sc.mode == "redact"
        assert sc.secret_scanner is True
        assert sc.pii_scanner is True
        assert sc.enforce_tool_confirmation is True

    def test_security_config_on_jarvis_config(self) -> None:
        cfg = JarvisConfig()
        assert isinstance(cfg.security, SecurityConfig)

    def test_security_config_loads_from_toml(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[security]\nmode = "block"\nscan_input = false\n')
        cfg = load_config(toml_file)
        assert cfg.security.mode == "block"
        assert cfg.security.scan_input is False

    def test_security_config_in_default_toml(self) -> None:
        output = generate_default_toml(HardwareInfo())
        assert "[security]" in output


class TestChannelConfig:
    def test_channel_config_defaults(self) -> None:
        cc = ChannelConfig()
        assert cc.enabled is False
        assert cc.default_agent == "simple"

    def test_channel_config_on_jarvis_config(self) -> None:
        cfg = JarvisConfig()
        assert isinstance(cfg.channel, ChannelConfig)

    def test_channel_config_loads_from_toml(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[channel]\nenabled = true\ndefault_channel = "telegram"\n'
        )
        cfg = load_config(toml_file)
        assert cfg.channel.enabled is True
        assert cfg.channel.default_channel == "telegram"

    def test_channel_config_in_default_toml(self) -> None:
        output = generate_default_toml(HardwareInfo())
        assert "[channel]" in output


# ---------------------------------------------------------------------------
# New config structure tests
# ---------------------------------------------------------------------------


class TestIntelligenceGenerationDefaults:
    def test_generation_fields_exist(self) -> None:
        ic = IntelligenceConfig()
        assert ic.temperature == 0.7
        assert ic.max_tokens == 1024
        assert ic.top_p == 0.9
        assert ic.top_k == 40
        assert ic.repetition_penalty == 1.0
        assert ic.stop_sequences == ""

    def test_custom_generation_values(self) -> None:
        ic = IntelligenceConfig(temperature=0.3, max_tokens=512, top_p=0.5)
        assert ic.temperature == 0.3
        assert ic.max_tokens == 512
        assert ic.top_p == 0.5


class TestAgentConfigNew:
    def test_new_fields(self) -> None:
        ac = AgentConfig()
        assert ac.objective == ""
        assert ac.system_prompt == ""
        assert ac.system_prompt_path == ""
        assert ac.context_from_memory is True
        assert ac.tools == ""
        assert ac.max_turns == 10

    def test_default_tools_backward_compat(self) -> None:
        ac = AgentConfig()
        ac.default_tools = "calculator,think"
        assert ac.tools == "calculator,think"
        assert ac.default_tools == "calculator,think"

    def test_no_temperature_or_max_tokens(self) -> None:
        ac = AgentConfig()
        assert (
            not hasattr(ac.__class__, "temperature")
            or isinstance(getattr(ac.__class__, "temperature", None), property) is False
        )


class TestNestedEngineConfig:
    def test_nested_access(self) -> None:
        ec = EngineConfig()
        assert ec.ollama.host == ""
        assert ec.vllm.host == "http://localhost:8000"
        assert ec.sglang.host == "http://localhost:30000"
        assert ec.llamacpp.host == "http://localhost:8080"
        assert ec.llamacpp.binary_path == ""

    def test_backward_compat_setter(self) -> None:
        ec = EngineConfig()
        ec.ollama_host = "http://custom:1234"
        assert ec.ollama.host == "http://custom:1234"
        assert ec.ollama_host == "http://custom:1234"

    def test_llamacpp_path_compat(self) -> None:
        ec = EngineConfig()
        ec.llamacpp_path = "/usr/bin/llama-server"
        assert ec.llamacpp.binary_path == "/usr/bin/llama-server"

    def test_loads_nested_toml(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[engine]\ndefault = "vllm"\n\n'
            '[engine.ollama]\nhost = "http://custom:11434"\n\n'
            '[engine.llamacpp]\nbinary_path = "/opt/llama"\n'
        )
        cfg = load_config(toml_file)
        assert cfg.engine.default == "vllm"
        assert cfg.engine.ollama.host == "http://custom:11434"
        assert cfg.engine.llamacpp.binary_path == "/opt/llama"

    def test_loads_old_flat_toml(self, tmp_path: Path) -> None:
        """Old flat engine keys still work via backward-compat properties."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[engine]\ndefault = "ollama"\n'
            'ollama_host = "http://old:11434"\n'
            'vllm_host = "http://old:8000"\n'
        )
        cfg = load_config(toml_file)
        assert cfg.engine.ollama.host == "http://old:11434"
        assert cfg.engine.vllm.host == "http://old:8000"


class TestNestedLearningConfig:
    def test_defaults(self) -> None:
        lc = LearningConfig()
        assert lc.enabled is False
        assert lc.update_interval == 100
        assert lc.auto_update is False
        assert lc.routing.policy == "heuristic"
        assert lc.routing.min_samples == 5
        assert lc.intelligence.policy == "none"
        assert lc.agent.policy == "none"
        assert lc.metrics.accuracy_weight == 0.6
        assert lc.metrics.latency_weight == 0.2

    def test_backward_compat_default_policy(self) -> None:
        lc = LearningConfig()
        assert lc.default_policy == "heuristic"
        lc.default_policy = "grpo"
        assert lc.routing.policy == "grpo"

    def test_backward_compat_intelligence_policy(self) -> None:
        lc = LearningConfig()
        lc.intelligence_policy = "sft"
        assert lc.intelligence.policy == "sft"

    def test_backward_compat_agent_policy(self) -> None:
        lc = LearningConfig()
        lc.agent_policy = "agent_advisor"
        assert lc.agent.policy == "agent_advisor"

    def test_backward_compat_reward_weights(self) -> None:
        lc = LearningConfig()
        lc.reward_weights = "latency=0.4,cost=0.3"
        assert lc.metrics.latency_weight == 0.4
        assert lc.metrics.cost_weight == 0.3

    def test_loads_nested_toml(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[learning]\nenabled = true\nupdate_interval = 50\n\n"
            '[learning.routing]\npolicy = "learned"\n\n'
            "[learning.metrics]\nlatency_weight = 0.5\n"
        )
        cfg = load_config(toml_file)
        assert cfg.learning.enabled is True
        assert cfg.learning.update_interval == 50
        assert cfg.learning.routing.policy == "learned"
        assert cfg.learning.metrics.latency_weight == 0.5

    def test_loads_old_flat_learning_toml(self, tmp_path: Path) -> None:
        """Old flat learning keys still work via backward-compat properties."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[learning]\ndefault_policy = "grpo"\n'
            'intelligence_policy = "sft"\n'
            'reward_weights = "latency=0.5"\n'
        )
        cfg = load_config(toml_file)
        assert cfg.learning.routing.policy == "grpo"
        assert cfg.learning.intelligence.policy == "sft"
        assert cfg.learning.metrics.latency_weight == 0.5


class TestBackwardCompatMigration:
    def test_agent_temperature_migrates_to_intelligence(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text("[agent]\ntemperature = 0.3\nmax_tokens = 512\n")
        cfg = load_config(toml_file)
        assert cfg.intelligence.temperature == 0.3
        assert cfg.intelligence.max_tokens == 512

    def test_memory_context_injection_migrates_to_agent(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text("[memory]\ncontext_injection = false\n")
        cfg = load_config(toml_file)
        assert cfg.agent.context_from_memory is False

    def test_tools_storage_context_injection_migrates(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[tools.storage]\ncontext_injection = false\ndefault_backend = "faiss"\n'
        )
        cfg = load_config(toml_file)
        assert cfg.agent.context_from_memory is False
        assert cfg.tools.storage.default_backend == "faiss"


class TestGenerateDefaultTomlNew:
    def test_nested_engine_sections(self) -> None:
        hw = HardwareInfo()
        toml_str = generate_default_toml(hw)
        assert "[engine.ollama]" in toml_str
        assert "[engine.vllm]" in toml_str
        assert "[engine.sglang]" in toml_str

    def test_intelligence_generation_params(self) -> None:
        hw = HardwareInfo()
        toml_str = generate_default_toml(hw)
        assert "temperature = 0.7" in toml_str
        assert "max_tokens = 1024" in toml_str

    def test_agent_new_fields(self) -> None:
        hw = HardwareInfo()
        toml_str = generate_default_toml(hw)
        assert "context_from_memory = true" in toml_str

    def test_learning_nested_sections(self) -> None:
        hw = HardwareInfo()
        toml_str = generate_default_toml(hw)
        assert "[learning.routing]" in toml_str
        assert 'policy = "heuristic"' in toml_str


# ---------------------------------------------------------------------------
# Sandbox config tests
# ---------------------------------------------------------------------------


class TestSandboxConfig:
    def test_defaults(self) -> None:
        sc = SandboxConfig()
        assert sc.enabled is False
        assert sc.image == "openjarvis-sandbox:latest"
        assert sc.timeout == 300
        assert sc.workspace == ""
        assert sc.mount_allowlist_path == ""
        assert sc.max_concurrent == 5
        assert sc.runtime == "docker"

    def test_custom_values(self) -> None:
        sc = SandboxConfig(
            enabled=True,
            image="custom:v2",
            timeout=600,
            runtime="podman",
        )
        assert sc.enabled is True
        assert sc.image == "custom:v2"
        assert sc.timeout == 600
        assert sc.runtime == "podman"

    def test_on_jarvis_config(self) -> None:
        cfg = JarvisConfig()
        assert isinstance(cfg.sandbox, SandboxConfig)
        assert cfg.sandbox.enabled is False

    def test_loads_from_toml(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[sandbox]\nenabled = true\ntimeout = 600\nruntime = "podman"\n'
        )
        cfg = load_config(toml_file)
        assert cfg.sandbox.enabled is True
        assert cfg.sandbox.timeout == 600
        assert cfg.sandbox.runtime == "podman"


# ---------------------------------------------------------------------------
# Scheduler config tests
# ---------------------------------------------------------------------------


class TestSchedulerConfig:
    def test_defaults(self) -> None:
        sc = SchedulerConfig()
        assert sc.enabled is False
        assert sc.poll_interval == 60
        assert sc.db_path == ""

    def test_custom_values(self) -> None:
        sc = SchedulerConfig(enabled=True, poll_interval=30, db_path="/tmp/sched.db")
        assert sc.enabled is True
        assert sc.poll_interval == 30
        assert sc.db_path == "/tmp/sched.db"

    def test_on_jarvis_config(self) -> None:
        cfg = JarvisConfig()
        assert isinstance(cfg.scheduler, SchedulerConfig)
        assert cfg.scheduler.enabled is False

    def test_loads_from_toml(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            "[scheduler]\nenabled = true\npoll_interval = 30\n"
            'db_path = "/tmp/sched.db"\n'
        )
        cfg = load_config(toml_file)
        assert cfg.scheduler.enabled is True
        assert cfg.scheduler.poll_interval == 30
        assert cfg.scheduler.db_path == "/tmp/sched.db"


# ---------------------------------------------------------------------------
# WhatsApp Baileys channel config tests
# ---------------------------------------------------------------------------


class TestApplyTomlSectionListNormalization:
    def test_apply_toml_section_list_to_str_field(self) -> None:
        """TOML arrays assigned to str-typed fields should be joined with ','."""
        from openjarvis.core.config import ToolsConfig, _apply_toml_section

        target = ToolsConfig()
        tools = ["code_interpreter", "web_search", "file_read"]
        _apply_toml_section(target, {"enabled": tools})
        assert isinstance(target.enabled, str)
        assert target.enabled == "code_interpreter,web_search,file_read"

    def test_apply_toml_section_list_to_property_setter(self) -> None:
        """TOML arrays passed to backward-compat property setters should be
        normalized to comma-separated strings, not passed as raw lists."""
        from openjarvis.core.config import _apply_toml_section

        target = LearningConfig()
        _apply_toml_section(
            target,
            {
                "reward_weights": ["accuracy=0.8", "latency=0.2"],
            },
        )
        assert target.metrics.accuracy_weight == 0.8
        assert target.metrics.latency_weight == 0.2

    def test_apply_toml_section_agent_tools_list(self) -> None:
        """Agent tools should work as a TOML array."""
        from openjarvis.core.config import _apply_toml_section

        target = AgentConfig()
        _apply_toml_section(
            target,
            {
                "tools": ["web_search", "http_request", "file_read"],
            },
        )
        assert isinstance(target.tools, str)
        assert target.tools == "web_search,http_request,file_read"


class TestWhatsAppBaileysChannelConfig:
    def test_defaults(self) -> None:
        wc = WhatsAppBaileysChannelConfig()
        assert wc.auth_dir == ""
        assert wc.assistant_name == "Jarvis"
        assert wc.assistant_has_own_number is False

    def test_custom_values(self) -> None:
        wc = WhatsAppBaileysChannelConfig(
            auth_dir="/tmp/wa",
            assistant_name="Andy",
            assistant_has_own_number=True,
        )
        assert wc.auth_dir == "/tmp/wa"
        assert wc.assistant_name == "Andy"
        assert wc.assistant_has_own_number is True

    def test_on_channel_config(self) -> None:
        cc = ChannelConfig()
        assert isinstance(cc.whatsapp_baileys, WhatsAppBaileysChannelConfig)

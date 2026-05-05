# src/openjarvis/mining/vllm_pearl.py
"""The v1 vllm-pearl mining provider.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from openjarvis.core.config import HardwareInfo
from openjarvis.core.registry import MinerRegistry
from openjarvis.mining._constants import (
    DEFAULT_GATEWAY_METRICS_PORT,
    DEFAULT_GATEWAY_RPC_PORT,
    DEFAULT_PEARL_MODEL,
    DEFAULT_VLLM_PORT,
    PEARL_IMAGE_TAG,
    SIDECAR_PATH,
)
from openjarvis.mining._discovery import detect_for_engine_model
from openjarvis.mining._docker import PearlDockerLauncher
from openjarvis.mining._metrics import parse_gateway_metrics
from openjarvis.mining._stubs import (
    MiningCapabilities,
    MiningConfig,
    MiningProvider,
    MiningStats,
    PoolTarget,
    Sidecar,
    SoloTarget,
)


class VllmPearlProvider(MiningProvider):
    """vLLM + Pearl Docker container, solo-mining only in v1."""

    provider_id = "vllm-pearl"

    def __init__(self, docker_client: Optional[Any] = None):
        if docker_client is None:
            import docker
            docker_client = docker.from_env()
        self._client = docker_client
        self._launcher = PearlDockerLauncher(client=docker_client)

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        return detect_for_engine_model(
            hw=hw, engine_id=engine_id, model=model, provider_id=cls.provider_id,
        )

    async def start(self, config: MiningConfig) -> None:
        if isinstance(config.submit_target, PoolTarget):
            raise NotImplementedError(
                "pool support is v2 — see openjarvis#XYZ. v1 only accepts "
                "submit_target='solo'."
            )
        assert isinstance(config.submit_target, SoloTarget)

        image = config.extra.get("docker_image_tag", PEARL_IMAGE_TAG)
        image = self._launcher.ensure_image(image)
        container = self._launcher.start(config, image=image)

        # Pull port assignments from extra (with sensible defaults).
        vllm_port = int(config.extra.get("vllm_port", DEFAULT_VLLM_PORT))
        gw_port = int(config.extra.get("gateway_port", DEFAULT_GATEWAY_RPC_PORT))
        gw_metrics = int(
            config.extra.get("gateway_metrics_port", DEFAULT_GATEWAY_METRICS_PORT)
        )
        model_name = config.extra.get("model", DEFAULT_PEARL_MODEL)

        Sidecar.write(SIDECAR_PATH, {
            "provider": self.provider_id,
            "vllm_endpoint": f"http://127.0.0.1:{vllm_port}/v1",
            "model": model_name,
            "gateway_url": f"http://127.0.0.1:{gw_port}",
            "gateway_metrics_url": f"http://127.0.0.1:{gw_metrics}",
            "container_id": getattr(container, "id", ""),
            "wallet_address": config.wallet_address,
            "started_at": int(time.time()),
        })

    async def stop(self) -> None:
        self._launcher.stop()
        Sidecar.remove(SIDECAR_PATH)

    def is_running(self) -> bool:
        return self._launcher.is_running()

    def stats(self) -> MiningStats:
        sidecar = Sidecar.read(SIDECAR_PATH)
        if sidecar is None:
            return MiningStats(provider_id=self.provider_id)
        url = sidecar.get("gateway_metrics_url")
        if not url:
            return MiningStats(provider_id=self.provider_id)
        try:
            resp = httpx.get(f"{url}/metrics", timeout=5.0)
            if resp.status_code != 200:
                return MiningStats(
                    provider_id=self.provider_id,
                    last_error=f"gateway HTTP {resp.status_code}",
                )
            return parse_gateway_metrics(resp.text, provider_id=self.provider_id)
        except Exception as e:  # noqa: BLE001
            return MiningStats(
                provider_id=self.provider_id,
                last_error=str(e).splitlines()[0],
            )


def ensure_registered() -> None:
    """Idempotent registration. Required because tests/conftest.py clears
    every registry before each test (see Spec A §4.2).
    """
    if not MinerRegistry.contains("vllm-pearl"):
        MinerRegistry.register_value("vllm-pearl", VllmPearlProvider)

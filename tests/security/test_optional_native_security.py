"""Security fallback behavior with an absent or broken native extension."""

import os
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from openjarvis.security.capabilities import CapabilityPolicy
from openjarvis.security.rate_limiter import RateLimitConfig, RateLimiter


@pytest.mark.parametrize("policy_class", [CapabilityPolicy, RateLimiter])
@pytest.mark.parametrize("error_class", [ImportError, RuntimeError])
def test_available_backend_initialization_errors_propagate(
    monkeypatch, policy_class, error_class
):
    import openjarvis._rust_bridge as bridge

    constructor = Mock(side_effect=error_class("broken native backend"))
    native = SimpleNamespace(CapabilityPolicy=constructor, RateLimiter=constructor)
    monkeypatch.setattr(bridge, "RUST_AVAILABLE", True)
    monkeypatch.setattr(bridge, "get_rust_module", lambda: native)
    with pytest.raises(error_class, match="broken native backend"):
        policy_class()


@pytest.mark.parametrize("use_native", [True, False])
def test_concurrent_checks_cannot_exceed_burst(monkeypatch, use_native):
    import openjarvis._rust_bridge as bridge

    if use_native and not bridge.RUST_AVAILABLE:
        pytest.skip("native extension unavailable")
    monkeypatch.setattr(bridge, "RUST_AVAILABLE", use_native)
    limiter = RateLimiter(RateLimitConfig(requests_per_minute=0, burst_size=5))
    with ThreadPoolExecutor(max_workers=16) as pool:
        decisions = list(pool.map(lambda _: limiter.check("same-key")[0], range(64)))
    assert sum(decisions) == 5


def test_security_enforcement_in_process_without_native_extension():
    # A fresh process exercises actual availability detection, not just a flag
    # patched after the extension has already been imported.
    probe = textwrap.dedent(
        """\
        import sys
        sys.modules['openjarvis_rust'] = None
        from openjarvis._rust_bridge import RUST_AVAILABLE
        from openjarvis.core.types import ToolCall, ToolResult
        from openjarvis.security.capabilities import CapabilityPolicy
        from openjarvis.security.rate_limiter import RateLimitConfig, RateLimiter
        from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec
        assert RUST_AVAILABLE is False
        effects = []
        class ProbeTool(BaseTool):
            tool_id = 'fallback_probe'
            @property
            def spec(self):
                return ToolSpec(name=self.tool_id, description='probe',
                                parameters={'type': 'object', 'properties': {}},
                                required_capabilities=['file:write'])
            def execute(self, **params):
                effects.append('executed')
                return ToolResult(tool_name=self.tool_id, content='ok', success=True)
        policy = CapabilityPolicy(default_deny=True)
        executor = ToolExecutor([ProbeTool()], capability_policy=policy, agent_id='a')
        call = ToolCall(id='probe', name='fallback_probe', arguments='{}')
        assert executor.execute(call).success is False
        assert effects == []
        policy.grant('a', 'file:write')
        assert executor.execute(call).success is True
        assert effects == ['executed']
        policy.deny('a', 'file:*')
        assert executor.execute(call).success is False
        assert effects == ['executed']
        limiter = RateLimiter(RateLimitConfig(requests_per_minute=0, burst_size=1))
        assert limiter.check('a') == (True, 0.0)
        assert limiter.check('a') == (False, float('inf'))
        limiter.reset('a')
        assert limiter.check('a') == (True, 0.0)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=dict(os.environ, PYTHONPATH="src"),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

"""Persisted channel bindings must preserve Ox Alpha's agent ban."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.server.app import _restore_sendblue_bindings


@pytest.mark.parametrize("model", ["openrouter/stealth/ox-alpha", "stealth/ox-alpha"])
@pytest.mark.parametrize("model_location", ["persisted", "state", "engine"])
def test_restore_sendblue_skips_ox_alpha_before_connecting(model, model_location):
    manager = MagicMock()
    manager.list_agents.return_value = [
        {
            "id": "agent-1",
            "config": {
                "model": model if model_location == "persisted" else "gemma4:31b"
            },
        }
    ]
    manager.list_channel_bindings.return_value = [
        {
            "channel_type": "sendblue",
            "config": {
                "api_key_id": "key-id",
                "api_secret_key": "secret",
                "from_number": "+15551234567",
            },
        }
    ]
    app = SimpleNamespace(
        state=SimpleNamespace(
            agent_manager=manager,
            model=model if model_location == "state" else "local-model",
            engine=SimpleNamespace(
                _model=model if model_location == "engine" else "local-model"
            ),
        )
    )

    with patch("openjarvis.channels.sendblue.SendBlueChannel") as channel:
        _restore_sendblue_bindings(app)

    channel.assert_not_called()
    assert not hasattr(app.state, "sendblue_channel")


def test_restore_sendblue_constructs_research_with_persisted_model():
    manager = MagicMock()
    manager.list_agents.return_value = [
        {"id": "agent-1", "config": {"model": "persisted-local"}}
    ]
    manager.list_channel_bindings.return_value = [
        {
            "channel_type": "sendblue",
            "config": {
                "api_key_id": "key-id",
                "api_secret_key": "secret",
                "from_number": "+15551234567",
            },
        }
    ]
    app = SimpleNamespace(
        state=SimpleNamespace(
            agent_manager=manager,
            model="state-local",
            engine=SimpleNamespace(_model="engine-local"),
        )
    )

    with (
        patch("openjarvis.channels.sendblue.SendBlueChannel"),
        patch(
            "openjarvis.server.agent_manager_routes._build_deep_research_tools",
            return_value=[MagicMock()],
        ),
        patch("openjarvis.agents.deep_research.DeepResearchAgent") as research,
        patch("openjarvis.server.channel_bridge.ChannelBridge"),
        patch("openjarvis.server.session_store.SessionStore"),
    ):
        _restore_sendblue_bindings(app)

    assert research.call_args.kwargs["model"] == "persisted-local"

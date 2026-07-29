from __future__ import annotations

import pytest

from openjarvis.codex import CodexPythonSdkBackend


class FakeAccountResponse:
    def __init__(self, account_type: str | None, *, error: str | None = None) -> None:
        self.account_type = account_type
        self.error = error

    def model_dump(self, **kwargs):
        del kwargs
        if self.error is not None:
            raise RuntimeError(self.error)
        account = None
        if self.account_type is not None:
            account = {
                "type": self.account_type,
                "email": "private@example.test",
                "accessToken": "must-not-escape",
            }
        return {"account": account, "requiresOpenaiAuth": True}


class FakeSdk:
    def __init__(self, response: FakeAccountResponse) -> None:
        self.response = response
        self.refresh_values: list[bool] = []
        self.closed = False

    async def account(self, *, refresh_token: bool):
        self.refresh_values.append(refresh_token)
        return self.response

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_healthcheck_accepts_existing_chatgpt_login() -> None:
    fake = FakeSdk(FakeAccountResponse("chatgpt"))
    captured = []
    backend = CodexPythonSdkBackend(
        sdk_factory=lambda spec: captured.append(spec) or fake,
        environment={
            "PATH": "safe",
            "CODEX_HOME": "safe-home",
            "OPENAI_API_KEY": "must-not-be-inherited",
        },
    )

    health = await backend.health()

    assert health.available is True
    assert health.authenticated is True
    assert health.auth_mode == "chatgpt"
    assert fake.refresh_values == [False]
    assert captured[0].experimental_api is False
    assert captured[0].codex_bin is None
    assert "OPENAI_API_KEY" not in captured[0].env
    assert "CODEX_HOME" in captured[0].env


@pytest.mark.asyncio
async def test_healthcheck_without_login_is_safe() -> None:
    backend = CodexPythonSdkBackend(
        sdk_factory=lambda spec: FakeSdk(FakeAccountResponse(None)),
        environment={},
    )

    health = await backend.health()

    assert health.available is True
    assert health.authenticated is False
    assert health.auth_mode is None
    assert "ChatGPT" in (health.detail or "")


@pytest.mark.asyncio
async def test_healthcheck_rejects_api_key_mode_without_fallback() -> None:
    backend = CodexPythonSdkBackend(
        sdk_factory=lambda spec: FakeSdk(FakeAccountResponse("apiKey")),
        environment={"OPENAI_API_KEY": "must-not-be-used"},
    )

    health = await backend.health()

    assert health.available is True
    assert health.authenticated is False
    assert health.auth_mode == "apiKey"
    assert "ChatGPT" in (health.detail or "")


@pytest.mark.asyncio
async def test_healthcheck_redacts_sdk_failures() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    backend = CodexPythonSdkBackend(
        sdk_factory=lambda spec: FakeSdk(
            FakeAccountResponse(None, error=f"Authorization: Bearer {secret}")
        ),
        environment={},
    )

    health = await backend.health()

    assert health.available is False
    assert secret not in (health.detail or "")


@pytest.mark.asyncio
async def test_close_is_ordered_and_idempotent() -> None:
    fake = FakeSdk(FakeAccountResponse("chatgpt"))
    backend = CodexPythonSdkBackend(
        sdk_factory=lambda spec: fake,
        environment={},
    )
    await backend.health()

    await backend.close()
    await backend.close()

    assert fake.closed is True

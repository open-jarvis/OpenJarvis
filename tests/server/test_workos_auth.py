"""WorkOS AuthKit authentication security regressions."""

from __future__ import annotations

import base64
import sys
import types
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from openjarvis.server.auth_middleware import (
    AuthMiddleware,
    _build_jwks_client,
    _verify_authkit_jwt,
    authenticate_websocket,
)


def _app(*, api_key: str = "", client_id: str = "client_test", jwks_client=None):
    app = FastAPI()

    @app.get("/v1/protected")
    async def protected(request: Request):
        return {
            "ok": True,
            "user_id": getattr(request.state, "user_id", ""),
        }

    @app.get("/health")
    async def health():
        return {"ok": True}

    app.add_middleware(
        AuthMiddleware,
        api_key=api_key,
        workos_client_id=client_id,
        workos_jwks_client=jwks_client,
    )
    return app


def _websocket(*, token: str):
    websocket = MagicMock()
    websocket.headers = {"authorization": f"Bearer {token}"}
    websocket.scope = {"subprotocols": []}
    return websocket


def test_missing_optional_dependency_fails_closed():
    client = TestClient(_app(jwks_client=None))

    assert client.get("/health").status_code == 200
    assert client.get("/v1/protected").status_code == 401
    response = client.get(
        "/v1/protected",
        headers={"Authorization": "Bearer header.payload.signature"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "AuthKit validation is unavailable"}


def test_static_api_key_still_works_if_workos_is_unavailable():
    client = TestClient(_app(api_key="static-secret", jwks_client=None))

    response = client.get(
        "/v1/protected",
        headers={"Authorization": "Bearer static-secret"},
    )

    assert response.status_code == 200


def test_valid_workos_claims_are_attached_to_request_state():
    with patch(
        "openjarvis.server.auth_middleware._verify_authkit_jwt",
        return_value={"sub": "user_123", "org_id": "org_123"},
    ) as verify:
        client = TestClient(_app(jwks_client=MagicMock()))
        response = client.get(
            "/v1/protected",
            headers={"Authorization": "Bearer header.payload.signature"},
        )

    assert response.status_code == 200
    assert response.json()["user_id"] == "user_123"
    assert verify.call_args.kwargs["audience"] == "client_test"


def test_jwt_decode_requires_configured_audience(monkeypatch):
    decode = MagicMock(return_value={"sub": "user_123"})
    monkeypatch.setitem(sys.modules, "jwt", types.SimpleNamespace(decode=decode))
    jwks_client = MagicMock()
    jwks_client.get_signing_key_from_jwt.return_value.key = "public-key"

    claims = _verify_authkit_jwt(
        "header.payload.signature",
        jwks_client,
        audience="client_expected",
    )

    assert claims == {"sub": "user_123"}
    decode.assert_called_once_with(
        "header.payload.signature",
        "public-key",
        algorithms=["RS256"],
        audience="client_expected",
    )


def test_wrong_audience_is_rejected(monkeypatch):
    decode = MagicMock(side_effect=ValueError("Audience does not match"))
    monkeypatch.setitem(sys.modules, "jwt", types.SimpleNamespace(decode=decode))
    jwks_client = MagicMock()
    jwks_client.get_signing_key_from_jwt.return_value.key = "public-key"

    assert (
        _verify_authkit_jwt(
            "header.payload.signature",
            jwks_client,
            audience="client_expected",
        )
        is None
    )


def test_real_rs256_token_requires_the_configured_audience():
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks_client = MagicMock()
    jwks_client.get_signing_key_from_jwt.return_value.key = private_key.public_key()
    valid = jwt.encode(
        {"sub": "user_123", "aud": "client_expected"},
        private_key,
        algorithm="RS256",
    )
    wrong_audience = jwt.encode(
        {"sub": "user_123", "aud": "client_other"},
        private_key,
        algorithm="RS256",
    )

    assert _verify_authkit_jwt(
        valid,
        jwks_client,
        audience="client_expected",
    ) == {"sub": "user_123", "aud": "client_expected"}
    assert (
        _verify_authkit_jwt(
            wrong_audience,
            jwks_client,
            audience="client_expected",
        )
        is None
    )


def test_jwks_client_requires_well_formed_workos_client_id():
    assert _build_jwks_client("https://attacker.example/jwks") is None
    assert _build_jwks_client("client_bad/path") is None


def test_jwks_client_missing_optional_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "jwt", None)

    assert _build_jwks_client("client_123ABC") is None


def test_jwks_client_uses_fixed_workos_origin(monkeypatch):
    created = {}

    class FakeJWKClient:
        def __init__(self, url, *, cache_keys):
            created.update(url=url, cache_keys=cache_keys)

        def get_signing_key_from_jwt(self, _token):
            return MagicMock(key="key")

    monkeypatch.setitem(
        sys.modules,
        "jwt",
        types.SimpleNamespace(PyJWKClient=FakeJWKClient),
    )

    client = _build_jwks_client("client_123ABC")

    assert isinstance(client, FakeJWKClient)
    assert created == {
        "url": "https://api.workos.com/sso/jwks/client_123ABC",
        "cache_keys": True,
    }


def test_workos_only_websocket_fails_closed_without_jwks():
    authorized, _ = authenticate_websocket(
        _websocket(token="header.payload.signature"),
        "",
        workos_client_id="client_test",
        workos_jwks_client=None,
    )

    assert authorized is False


def test_workos_websocket_validates_token(monkeypatch):
    verify = MagicMock(return_value={"sub": "user_123"})
    monkeypatch.setattr(
        "openjarvis.server.auth_middleware._verify_authkit_jwt",
        verify,
    )
    jwks_client = MagicMock()

    authorized, _ = authenticate_websocket(
        _websocket(token="header.payload.signature"),
        "",
        workos_client_id="client_test",
        workos_jwks_client=jwks_client,
    )

    assert authorized is True
    verify.assert_called_once_with(
        "header.payload.signature",
        jwks_client,
        audience="client_test",
    )


def test_workos_websocket_accepts_browser_subprotocol(monkeypatch):
    token = "header.payload.signature"
    encoded = base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")
    websocket = MagicMock()
    websocket.headers = {}
    websocket.scope = {
        "subprotocols": [
            "openjarvis.auth.v1",
            f"openjarvis.key.b64url.{encoded}",
        ]
    }
    monkeypatch.setattr(
        "openjarvis.server.auth_middleware._verify_authkit_jwt",
        MagicMock(return_value={"sub": "user_123"}),
    )

    authorized, selected = authenticate_websocket(
        websocket,
        "",
        workos_client_id="client_test",
        workos_jwks_client=MagicMock(),
    )

    assert authorized is True
    assert selected == "openjarvis.auth.v1"

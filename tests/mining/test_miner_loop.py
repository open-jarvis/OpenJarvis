"""Tests for openjarvis.mining._miner_loop_main."""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_mining_info_result():
    """Mock getMiningInfo result — base64-encoded incomplete header + target."""
    return {
        "incomplete_header_bytes": base64.b64encode(b"\x00" * 76).decode(),
        "target": 0x1D2FFFFF,
    }


def test_decode_mining_info_returns_header_bytes_and_target(fake_mining_info_result):
    from openjarvis.mining._miner_loop_main import _decode_mining_info

    header_bytes, target = _decode_mining_info(fake_mining_info_result)
    assert isinstance(header_bytes, (bytes, bytearray))
    assert len(header_bytes) == 76
    assert target == 0x1D2FFFFF


def test_encode_plain_proof_returns_to_base64_result():
    """_encode_plain_proof returns plain_proof.to_base64() directly.

    No double-encode: to_base64() already returns a base64 string.
    """
    from openjarvis.mining._miner_loop_main import _encode_plain_proof

    fake_proof = MagicMock()
    fake_proof.to_base64.return_value = "ABCabc012=="
    encoded = _encode_plain_proof(fake_proof)
    assert encoded == "ABCabc012=="
    fake_proof.to_base64.assert_called_once()


def test_jsonrpc_envelope_shape():
    """The JSON-RPC envelope conforms to gateway's JSON_RPC_SCHEMA."""
    from openjarvis.mining._miner_loop_main import _make_request

    req = _make_request("getMiningInfo", {}, request_id=42)
    assert req["jsonrpc"] == "2.0"
    assert req["method"] == "getMiningInfo"
    assert req["id"] == 42
    assert req["params"] == {}


def test_open_gateway_connection_retries_until_listener_ready(monkeypatch):
    """Initial gateway connect has startup-race retry/backoff."""
    from openjarvis.mining import _miner_loop_main

    calls = 0
    fake_reader = object()
    fake_writer = object()

    async def fake_open_connection(host, port):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionRefusedError("not ready")
        return fake_reader, fake_writer

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)

    reader, writer = asyncio.run(
        _miner_loop_main._open_gateway_connection(
            "127.0.0.1",
            18337,
            timeout_seconds=1.0,
            retry_seconds=0.0,
        )
    )

    assert calls == 3
    assert reader is fake_reader
    assert writer is fake_writer

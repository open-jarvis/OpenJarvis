"""Tests for MCP protocol message types."""

from __future__ import annotations

import json

from openjarvis.mcp.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    MCPError,
    MCPNotification,
    MCPRequest,
    MCPResponse,
)


class TestMCPRequest:
    def test_serialize_deserialize(self):
        req = MCPRequest(method="tools/list", params={"cursor": None}, id=1)
        data = req.to_json()
        restored = MCPRequest.from_json(data)
        assert restored.method == "tools/list"
        assert restored.id == 1
        assert restored.jsonrpc == "2.0"

    def test_initialize_request(self):
        req = MCPRequest(method="initialize", params={}, id=1)
        parsed = json.loads(req.to_json())
        assert parsed["method"] == "initialize"
        assert parsed["jsonrpc"] == "2.0"
        assert parsed["id"] == 1

    def test_tools_list_request(self):
        req = MCPRequest(method="tools/list", id=2)
        parsed = json.loads(req.to_json())
        assert parsed["method"] == "tools/list"

    def test_tools_call_request(self):
        req = MCPRequest(
            method="tools/call",
            params={"name": "calculator", "arguments": {"expression": "2+2"}},
            id=3,
        )
        parsed = json.loads(req.to_json())
        assert parsed["method"] == "tools/call"
        assert parsed["params"]["name"] == "calculator"
        assert parsed["params"]["arguments"]["expression"] == "2+2"

    def test_default_params_empty(self):
        req = MCPRequest(method="test")
        assert req.params == {}

    def test_string_id(self):
        req = MCPRequest(method="test", id="abc-123")
        data = req.to_json()
        restored = MCPRequest.from_json(data)
        assert restored.id == "abc-123"

    def test_from_json_missing_params(self):
        raw = json.dumps({"jsonrpc": "2.0", "method": "test", "id": 1})
        req = MCPRequest.from_json(raw)
        assert req.params == {}


class TestMCPResponse:
    def test_serialize_deserialize_success(self):
        resp = MCPResponse(result={"tools": []}, id=1)
        data = resp.to_json()
        restored = MCPResponse.from_json(data)
        assert restored.result == {"tools": []}
        assert restored.error is None
        assert restored.id == 1

    def test_serialize_deserialize_error(self):
        resp = MCPResponse.error_response(1, METHOD_NOT_FOUND, "Not found")
        data = resp.to_json()
        restored = MCPResponse.from_json(data)
        assert restored.error is not None
        assert restored.error["code"] == METHOD_NOT_FOUND
        assert restored.error["message"] == "Not found"

    def test_error_response_factory(self):
        resp = MCPResponse.error_response(42, INVALID_PARAMS, "Bad params")
        assert resp.error["code"] == INVALID_PARAMS
        assert resp.error["message"] == "Bad params"
        assert resp.id == 42
        assert resp.result is None

    def test_error_response_with_data(self):
        resp = MCPResponse.error_response(
            1,
            INTERNAL_ERROR,
            "Oops",
            data={"detail": "stack"},
        )
        assert resp.error["data"] == {"detail": "stack"}

    def test_success_response(self):
        resp = MCPResponse(result={"value": 42}, id=5)
        parsed = json.loads(resp.to_json())
        assert "result" in parsed
        assert "error" not in parsed
        assert parsed["result"]["value"] == 42

    def test_error_excludes_result(self):
        resp = MCPResponse.error_response(1, PARSE_ERROR, "Parse error")
        parsed = json.loads(resp.to_json())
        assert "error" in parsed
        assert "result" not in parsed

    def test_jsonrpc_version(self):
        resp = MCPResponse(result={}, id=1)
        parsed = json.loads(resp.to_json())
        assert parsed["jsonrpc"] == "2.0"


class TestMCPNotification:
    def test_format(self):
        notif = MCPNotification(method="notifications/initialized", params={})
        parsed = json.loads(notif.to_json())
        assert parsed["method"] == "notifications/initialized"
        assert parsed["jsonrpc"] == "2.0"

    def test_no_id_field(self):
        notif = MCPNotification(method="test")
        parsed = json.loads(notif.to_json())
        assert "id" not in parsed

    def test_with_params(self):
        notif = MCPNotification(method="progress", params={"percent": 50})
        parsed = json.loads(notif.to_json())
        assert parsed["params"]["percent"] == 50


class TestMCPError:
    def test_error_is_exception(self):
        err = MCPError(code=METHOD_NOT_FOUND, message="Not found")
        assert isinstance(err, Exception)

    def test_error_str(self):
        err = MCPError(code=-32601, message="Not found")
        assert "-32601" in str(err)
        assert "Not found" in str(err)

    def test_error_with_data(self):
        err = MCPError(code=INTERNAL_ERROR, message="Oops", data={"trace": "..."})
        assert err.data == {"trace": "..."}


class TestErrorCodes:
    def test_parse_error(self):
        assert PARSE_ERROR == -32700

    def test_invalid_request(self):
        assert INVALID_REQUEST == -32600

    def test_method_not_found(self):
        assert METHOD_NOT_FOUND == -32601

    def test_invalid_params(self):
        assert INVALID_PARAMS == -32602

    def test_internal_error(self):
        assert INTERNAL_ERROR == -32603

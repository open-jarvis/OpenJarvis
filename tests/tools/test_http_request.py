"""Tests for the HTTP request tool with SSRF protection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from openjarvis.tools.http_request import HttpRequestTool


@pytest.fixture(autouse=True)
def _force_httpx_fallback():
    """Patch the Rust HTTP tool so it raises, falling back to httpx.

    The Rust backend makes real HTTP requests that bypass respx mocks.
    By making the Rust HttpRequestTool().execute() raise, the tool falls
    through to the httpx code path where respx interception works.
    """
    mock_rust = MagicMock()
    mock_rust.HttpRequestTool.return_value.execute.side_effect = RuntimeError(
        "mocked out"
    )
    with patch(
        "openjarvis._rust_bridge.get_rust_module",
        return_value=mock_rust,
    ):
        yield


class TestHttpRequestTool:
    def test_spec_name_and_category(self):
        tool = HttpRequestTool()
        assert tool.spec.name == "http_request"
        assert tool.spec.category == "network"

    def test_spec_required_capabilities(self):
        tool = HttpRequestTool()
        assert "network:fetch" in tool.spec.required_capabilities

    def test_spec_parameters_require_url(self):
        tool = HttpRequestTool()
        assert "url" in tool.spec.parameters["properties"]
        assert "url" in tool.spec.parameters["required"]

    def test_tool_id(self):
        tool = HttpRequestTool()
        assert tool.tool_id == "http_request"

    def test_to_openai_function(self):
        tool = HttpRequestTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "http_request"
        assert "url" in fn["function"]["parameters"]["properties"]

    def test_no_url(self):
        tool = HttpRequestTool()
        result = tool.execute()
        assert result.success is False
        assert "No URL" in result.content

    def test_empty_url(self):
        tool = HttpRequestTool()
        result = tool.execute(url="")
        assert result.success is False
        assert "No URL" in result.content

    def test_ssrf_blocked_private_ip(self):
        """Request to private IP should be blocked by SSRF protection."""
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf") as mock_ssrf:
            mock_ssrf.return_value = "URL resolves to private IP: 192.168.1.1"
            result = tool.execute(url="http://192.168.1.1/admin")
        assert result.success is False
        assert "SSRF protection" in result.content
        assert "private IP" in result.content

    def test_ssrf_blocked_metadata_endpoint(self):
        """Request to cloud metadata endpoint should be blocked."""
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf") as mock_ssrf:
            mock_ssrf.return_value = (
                "Blocked host: 169.254.169.254 (cloud metadata endpoint)"
            )
            result = tool.execute(url="http://169.254.169.254/latest/meta-data/")
        assert result.success is False
        assert "SSRF protection" in result.content
        assert "metadata" in result.content.lower() or "Blocked host" in result.content

    @respx.mock
    def test_successful_get(self):
        """Successful GET request returns response content and metadata."""
        respx.get("https://api.example.com/data").mock(
            return_value=httpx.Response(
                200,
                text='{"key": "value"}',
                headers={"content-type": "application/json"},
            )
        )
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            result = tool.execute(url="https://api.example.com/data")
        assert result.success is True
        assert '"key": "value"' in result.content
        assert result.metadata["status_code"] == 200
        assert "application/json" in result.metadata["content_type"]
        assert "elapsed_ms" in result.metadata

    @respx.mock
    def test_post_with_body(self):
        """POST request with body sends content correctly."""
        respx.post("https://api.example.com/submit").mock(
            return_value=httpx.Response(
                201,
                text='{"id": 42}',
                headers={"content-type": "application/json"},
            )
        )
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            result = tool.execute(
                url="https://api.example.com/submit",
                method="POST",
                body='{"name": "test"}',
                headers={"Content-Type": "application/json"},
            )
        assert result.success is True
        assert '"id": 42' in result.content
        assert result.metadata["status_code"] == 201

    @respx.mock
    def test_put_method(self):
        """PUT request works correctly."""
        respx.put("https://api.example.com/resource/1").mock(
            return_value=httpx.Response(200, text="updated")
        )
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            result = tool.execute(
                url="https://api.example.com/resource/1",
                method="PUT",
                body="new data",
            )
        assert result.success is True
        assert "updated" in result.content

    @respx.mock
    def test_delete_method(self):
        """DELETE request works correctly."""
        respx.delete("https://api.example.com/resource/1").mock(
            return_value=httpx.Response(204, text="")
        )
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            result = tool.execute(
                url="https://api.example.com/resource/1",
                method="DELETE",
            )
        assert result.success is True

    @respx.mock
    def test_head_method(self):
        """HEAD request works correctly."""
        respx.head("https://api.example.com/check").mock(
            return_value=httpx.Response(
                200,
                text="",
                headers={"x-custom": "header-value"},
            )
        )
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            result = tool.execute(
                url="https://api.example.com/check",
                method="HEAD",
            )
        assert result.success is True
        assert result.metadata["status_code"] == 200

    def test_timeout_handling(self):
        """Timeout should produce a clear error."""
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            with patch(
                "openjarvis.tools.http_request.httpx.request",
                side_effect=httpx.TimeoutException("timed out"),
            ):
                result = tool.execute(url="https://slow.example.com", timeout=5)
        assert result.success is False
        assert "timed out" in result.content.lower()

    def test_request_error(self):
        """Connection error should produce a clear error."""
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            with patch(
                "openjarvis.tools.http_request.httpx.request",
                side_effect=httpx.ConnectError("Connection refused"),
            ):
                result = tool.execute(url="https://down.example.com")
        assert result.success is False
        assert "Request error" in result.content

    def test_method_validation(self):
        """Invalid HTTP method should be rejected."""
        tool = HttpRequestTool()
        result = tool.execute(url="https://example.com", method="TRACE")
        assert result.success is False
        assert "Unsupported HTTP method" in result.content
        assert "TRACE" in result.content

    def test_method_case_insensitive(self):
        """Method should be case-insensitive."""
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            with respx.mock:
                respx.get("https://api.example.com/data").mock(
                    return_value=httpx.Response(200, text="ok")
                )
                result = tool.execute(url="https://api.example.com/data", method="get")
        assert result.success is True

    @respx.mock
    def test_response_truncation(self):
        """Response larger than 1 MB should be truncated."""
        large_body = "x" * 2_000_000  # 2 MB
        respx.get("https://api.example.com/large").mock(
            return_value=httpx.Response(200, text=large_body)
        )
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            result = tool.execute(url="https://api.example.com/large")
        assert result.success is True
        assert "[Response truncated at 1 MB]" in result.content
        assert result.metadata["truncated"] is True

    @respx.mock
    def test_response_not_truncated_when_small(self):
        """Response smaller than 1 MB should not be truncated."""
        small_body = "hello world"
        respx.get("https://api.example.com/small").mock(
            return_value=httpx.Response(200, text=small_body)
        )
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            result = tool.execute(url="https://api.example.com/small")
        assert result.success is True
        assert result.content == "hello world"
        assert result.metadata["truncated"] is False

    @respx.mock
    def test_metadata_includes_headers(self):
        """Response metadata should include headers dict."""
        respx.get("https://api.example.com/data").mock(
            return_value=httpx.Response(
                200,
                text="ok",
                headers={
                    "content-type": "text/plain",
                    "x-request-id": "abc123",
                },
            )
        )
        tool = HttpRequestTool()
        with patch("openjarvis.tools.http_request.check_ssrf", return_value=None):
            result = tool.execute(url="https://api.example.com/data")
        assert isinstance(result.metadata["headers"], dict)
        assert result.metadata["headers"]["x-request-id"] == "abc123"


__all__ = ["TestHttpRequestTool"]

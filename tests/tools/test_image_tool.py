"""Tests for the image_generate tool."""

from __future__ import annotations

import builtins
import sys
from unittest.mock import MagicMock

from friday_ai.tools.image_tool import ImageGenerateTool


class TestImageGenerateTool:
    def test_spec(self):
        tool = ImageGenerateTool()
        assert tool.spec.name == "image_generate"
        assert tool.spec.category == "media"
        assert "prompt" in tool.spec.parameters["properties"]
        assert "prompt" in tool.spec.parameters["required"]
        assert tool.spec.required_capabilities == ["network:fetch"]

    def test_tool_id(self):
        tool = ImageGenerateTool()
        assert tool.tool_id == "image_generate"

    def test_no_prompt(self):
        tool = ImageGenerateTool()
        result = tool.execute(prompt="")
        assert result.success is False
        assert "No prompt" in result.content

    def test_no_prompt_param(self):
        tool = ImageGenerateTool()
        result = tool.execute()
        assert result.success is False
        assert "No prompt" in result.content

    def test_invalid_size(self):
        tool = ImageGenerateTool()
        result = tool.execute(prompt="a cat", size="999x999")
        assert result.success is False
        assert "Invalid size" in result.content

    def test_unsupported_provider(self):
        tool = ImageGenerateTool()
        result = tool.execute(prompt="a cat", provider="midjourney")
        assert result.success is False
        assert "Unsupported provider" in result.content

    def test_openai_not_installed(self, monkeypatch):
        """Simulate openai package not being installed."""
        monkeypatch.delitem(sys.modules, "openai", raising=False)
        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("No module named 'openai'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = ImageGenerateTool()
        result = tool.execute(prompt="a cat")
        assert result.success is False
        assert "openai package not installed" in result.content

    def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        mock_openai = MagicMock()
        monkeypatch.setitem(sys.modules, "openai", mock_openai)

        tool = ImageGenerateTool()
        result = tool.execute(prompt="a cat")
        assert result.success is False
        assert "No API key" in result.content

    def test_successful_generation(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        mock_image_data = MagicMock()
        mock_image_data.url = "https://example.com/image.png"

        mock_response = MagicMock()
        mock_response.data = [mock_image_data]

        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        mock_openai = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        monkeypatch.setitem(sys.modules, "openai", mock_openai)

        tool = ImageGenerateTool()
        result = tool.execute(prompt="a cat on a mat")
        assert result.success is True
        assert result.content == "https://example.com/image.png"
        assert result.metadata["url"] == "https://example.com/image.png"
        assert result.metadata["size"] == "1024x1024"
        assert result.metadata["provider"] == "openai"

    def test_save_to_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        mock_image_data = MagicMock()
        mock_image_data.url = "https://example.com/image.png"

        mock_response = MagicMock()
        mock_response.data = [mock_image_data]

        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        mock_openai = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        monkeypatch.setitem(sys.modules, "openai", mock_openai)

        # Mock httpx for downloading
        import httpx

        mock_http_resp = MagicMock()
        mock_http_resp.content = b"\x89PNG\r\n\x1a\nfake-image-data"
        mock_http_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_http_resp))

        output_file = tmp_path / "output.png"
        tool = ImageGenerateTool()
        result = tool.execute(
            prompt="a cat",
            output_path=str(output_file),
        )
        assert result.success is True
        assert output_file.exists()
        assert output_file.read_bytes() == b"\x89PNG\r\n\x1a\nfake-image-data"

    def test_api_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.images.generate.side_effect = RuntimeError("Rate limit exceeded")

        mock_openai = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        monkeypatch.setitem(sys.modules, "openai", mock_openai)

        tool = ImageGenerateTool()
        result = tool.execute(prompt="a cat")
        assert result.success is False
        assert "Image generation error" in result.content

    def test_to_openai_function(self):
        tool = ImageGenerateTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "image_generate"

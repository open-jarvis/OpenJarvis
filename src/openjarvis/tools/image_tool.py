"""Image generation tool — generate images via OpenAI DALL-E."""

from __future__ import annotations

import os
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_VALID_SIZES = {"256x256", "512x512", "1024x1024"}


@ToolRegistry.register("image_generate")
class ImageGenerateTool(BaseTool):
    """Generate images from text descriptions via OpenAI DALL-E."""

    tool_id = "image_generate"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="image_generate",
            description=(
                "Generate an image from a text description. Returns the image URL."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Text description of the image to generate.",
                    },
                    "size": {
                        "type": "string",
                        "description": (
                            "Image size: '256x256', '512x512', or '1024x1024'."
                            " Default '1024x1024'."
                        ),
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional file path to save the image to.",
                    },
                    "provider": {
                        "type": "string",
                        "description": "Image generation provider. Default 'openai'.",
                    },
                },
                "required": ["prompt"],
            },
            category="media",
            required_capabilities=["network:fetch"],
        )

    def execute(self, **params: Any) -> ToolResult:
        prompt = params.get("prompt", "")
        if not prompt:
            return ToolResult(
                tool_name="image_generate",
                content="No prompt provided.",
                success=False,
            )

        size = params.get("size", "1024x1024")
        if size not in _VALID_SIZES:
            return ToolResult(
                tool_name="image_generate",
                content=(
                    f"Invalid size '{size}'."
                    f" Must be one of: {', '.join(sorted(_VALID_SIZES))}."
                ),
                success=False,
            )

        provider = params.get("provider", "openai")
        output_path = params.get("output_path")

        if provider != "openai":
            return ToolResult(
                tool_name="image_generate",
                content=(
                    f"Unsupported provider '{provider}'. Only 'openai' is supported."
                ),
                success=False,
            )

        try:
            import openai
        except ImportError:
            return ToolResult(
                tool_name="image_generate",
                content=(
                    "openai package not installed. Install with: pip install openai"
                ),
                success=False,
            )

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return ToolResult(
                tool_name="image_generate",
                content="No API key configured. Set OPENAI_API_KEY.",
                success=False,
            )

        try:
            client = openai.OpenAI()
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                n=1,
            )
            url = response.data[0].url
        except Exception as exc:
            return ToolResult(
                tool_name="image_generate",
                content=f"Image generation error: {exc}",
                success=False,
            )

        # Optionally save to file
        if output_path:
            try:
                import httpx

                resp = httpx.get(url, follow_redirects=True, timeout=60.0)
                resp.raise_for_status()
                from pathlib import Path

                Path(output_path).write_bytes(resp.content)
            except Exception as exc:
                return ToolResult(
                    tool_name="image_generate",
                    content=(f"Image generated but failed to save: {exc}. URL: {url}"),
                    success=False,
                    metadata={"url": url, "size": size, "provider": provider},
                )

        return ToolResult(
            tool_name="image_generate",
            content=url,
            success=True,
            metadata={"url": url, "size": size, "provider": provider},
        )


__all__ = ["ImageGenerateTool"]

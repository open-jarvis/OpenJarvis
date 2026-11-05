"""Exercise the gateway contract through the real SDK without network access."""

from __future__ import annotations

import json

import pytest

from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import ResponseFormat
from openjarvis.engine.cloud import CloudEngine, estimate_cost


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["generate", "stream", "stream_full"])
@pytest.mark.parametrize("format_type", ["json_object", "json_schema"])
async def test_structured_output_reaches_gateway_in_all_request_paths(
    mode, format_type
):
    import httpx
    import openai

    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }
    response_format = ResponseFormat(type=format_type, schema=schema)
    sent = []

    def respond(request):
        body = json.loads(request.content)
        sent.append(body)
        assert (
            str(request.url) == "https://api.cheaperinference.com/v1/chat/completions"
        )
        if body.get("stream"):
            events = [
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "gpt-5.4-mini",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": '{"ok":true}'},
                            "finish_reason": "stop",
                        }
                    ],
                }
            ]
            data = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=data + "data: [DONE]\n\n",
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-5.4-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"ok":true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    with openai.OpenAI(
        api_key="test-key",
        base_url="https://api.cheaperinference.com/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        engine = CloudEngine()
        engine._cheaperinference_client = client
        kwargs = {
            "model": "cheaperinference/gpt-5.4-mini",
            "max_tokens": 32,
            "response_format": response_format,
            "top_p": 0.8,
        }
        messages = [Message(role=Role.USER, content="Return a JSON object")]
        if mode == "generate":
            assert engine.generate(messages, **kwargs)["content"] == '{"ok":true}'
        else:
            chunks = [
                chunk async for chunk in getattr(engine, mode)(messages, **kwargs)
            ]
            assert chunks

    assert len(sent) == 1
    expected = {"type": format_type}
    if format_type == "json_schema":
        expected["json_schema"] = {"name": "response", "schema": schema}
    assert sent[0]["response_format"] == expected
    assert sent[0]["top_p"] == 0.8
    assert sent[0]["model"] == "gpt-5.4-mini"


@pytest.mark.parametrize(
    "model,input_rate,output_rate",
    [
        ("gpt-5.4-mini", 0.4875, 2.925),
        ("gpt-5.4", 1.625, 9.75),
        ("claude-sonnet-5", 1.3, 6.5),
        ("gemini-3.1-pro", 1.650244, 9.901461),
    ],
)
def test_advertised_gateway_models_have_cost_estimates(model, input_rate, output_rate):
    cost = estimate_cost(f"cheaperinference/{model}", 10_000, 1_000)
    assert cost == pytest.approx(input_rate * 0.01 + output_rate * 0.001)


@pytest.mark.parametrize(
    "model,threshold,short_rates,long_rates",
    [
        ("gpt-5.4", 272_000, (1.625, 9.75), (3.25, 14.625)),
        ("gemini-3.1-pro", 200_000, (1.650244, 9.901461), (3.300487, 14.852192)),
    ],
)
def test_gateway_long_context_estimates_apply_to_the_whole_request(
    model, threshold, short_rates, long_rates
):
    key = f"cheaperinference/{model}"
    assert estimate_cost(key, threshold, 1_000) == pytest.approx(
        threshold / 1_000_000 * short_rates[0] + 0.001 * short_rates[1]
    )
    assert estimate_cost(key, threshold + 1, 1_000) == pytest.approx(
        (threshold + 1) / 1_000_000 * long_rates[0] + 0.001 * long_rates[1]
    )


def test_gateway_mini_does_not_inherit_larger_models_long_context_tier():
    assert estimate_cost(
        "cheaperinference/gpt-5.4-mini", 300_000, 1_000
    ) == pytest.approx(0.3 * 0.4875 + 0.001 * 2.925)

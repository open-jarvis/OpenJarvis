from __future__ import annotations


def test_anthropic_cache_breakpoint_added():
    from openjarvis.engine.cloud import _annotate_anthropic_cache

    messages = [
        {"role": "system", "content": "You are Jarvis. ## Persona\nHelpful assistant."},
        {"role": "user", "content": "Hello"},
    ]
    annotated = _annotate_anthropic_cache(messages)
    system_msg = annotated[0]
    # System message content should be a list with cache_control
    assert isinstance(system_msg["content"], list)
    assert system_msg["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_non_system_messages_unchanged():
    from openjarvis.engine.cloud import _annotate_anthropic_cache

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
    annotated = _annotate_anthropic_cache(messages)
    assert annotated[0]["content"] == "Hello"
    assert annotated[1]["content"] == "Hi there"


def test_already_list_content_gets_cache_control():
    from openjarvis.engine.cloud import _annotate_anthropic_cache

    messages = [
        {"role": "system", "content": [{"type": "text", "text": "You are Jarvis."}]},
    ]
    annotated = _annotate_anthropic_cache(messages)
    assert annotated[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

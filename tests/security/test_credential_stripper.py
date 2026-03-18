from __future__ import annotations


def test_strips_openai_key():
    from openjarvis.security.credential_stripper import CredentialStripper

    stripper = CredentialStripper()
    text = (
        "Error: auth failed with key "
        "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234"
    )
    result = stripper.strip(text)
    assert "sk-proj-" not in result
    assert "[REDACTED:" in result


def test_strips_aws_key():
    from openjarvis.security.credential_stripper import CredentialStripper

    stripper = CredentialStripper()
    text = "Using credentials AKIAIOSFODNN7EXAMPLE for access"
    result = stripper.strip(text)
    assert "AKIA" not in result
    assert "[REDACTED:" in result


def test_strips_github_token():
    from openjarvis.security.credential_stripper import CredentialStripper

    stripper = CredentialStripper()
    text = "Token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
    result = stripper.strip(text)
    assert "ghp_" not in result


def test_preserves_normal_text():
    from openjarvis.security.credential_stripper import CredentialStripper

    stripper = CredentialStripper()
    text = "The function returned 42 results."
    result = stripper.strip(text)
    assert result == text


def test_tool_output_wrapping():
    from openjarvis.security.credential_stripper import wrap_tool_output

    content = "Search results: found 3 items"
    wrapped = wrap_tool_output("web_search", content, success=True)
    assert '<tool_result name="web_search" status="success">' in wrapped
    assert "Search results" in wrapped
    assert "</tool_result>" in wrapped

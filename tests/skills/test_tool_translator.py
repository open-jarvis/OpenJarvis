"""Tests for ToolTranslator — translate external tool names to OpenJarvis."""

from __future__ import annotations

from openjarvis.skills.tool_translator import TOOL_TRANSLATION, ToolTranslator


class TestTranslationTable:
    def test_bash_translates_to_shell_exec(self):
        assert TOOL_TRANSLATION["Bash"] == "shell_exec"

    def test_read_translates_to_file_read(self):
        assert TOOL_TRANSLATION["Read"] == "file_read"

    def test_write_translates_to_file_write(self):
        assert TOOL_TRANSLATION["Write"] == "file_write"

    def test_websearch_translates(self):
        assert TOOL_TRANSLATION["WebSearch"] == "web_search"


class TestMarkdownTranslation:
    def test_translate_inline_tool_reference(self):
        translator = ToolTranslator()
        body = "Use the Bash tool to run commands."
        new_body, untranslated = translator.translate_markdown(body)
        assert "shell_exec" in new_body
        assert "Bash" not in new_body
        assert untranslated == []

    def test_translate_multiple_tools(self):
        translator = ToolTranslator()
        body = "First use Read to load the file, then Write to save it."
        new_body, _ = translator.translate_markdown(body)
        assert "file_read" in new_body
        assert "file_write" in new_body

    def test_unknown_tool_collected(self):
        translator = ToolTranslator()
        body = "Use the QuantumComputer tool."
        new_body, untranslated = translator.translate_markdown(body)
        assert "QuantumComputer" in untranslated
        assert "QuantumComputer" in new_body  # left in place

    def test_word_boundary_respected(self):
        """'Read' should not match 'Reader' or 'Reading'."""
        translator = ToolTranslator()
        body = "The Reader processes Reading material."
        new_body, _ = translator.translate_markdown(body)
        assert "Reader" in new_body
        assert "Reading" in new_body
        assert "file_read" not in new_body

    def test_empty_body(self):
        translator = ToolTranslator()
        new_body, untranslated = translator.translate_markdown("")
        assert new_body == ""
        assert untranslated == []


class TestAllowedToolsTranslation:
    def test_translate_space_delimited(self):
        translator = ToolTranslator()
        new_field, untranslated = translator.translate_allowed_tools("Bash Read Write")
        assert "shell_exec" in new_field
        assert "file_read" in new_field
        assert "file_write" in new_field
        assert untranslated == []

    def test_translate_with_arguments(self):
        translator = ToolTranslator()
        # Spec example: Bash(git:*) Bash(jq:*) Read
        new_field, _ = translator.translate_allowed_tools("Bash(git:*) Bash(jq:*) Read")
        assert "shell_exec(git:*)" in new_field
        assert "shell_exec(jq:*)" in new_field
        assert "file_read" in new_field

    def test_unknown_in_allowed_tools_collected(self):
        translator = ToolTranslator()
        new_field, untranslated = translator.translate_allowed_tools("Bash UnknownTool")
        assert "UnknownTool" in untranslated

"""`--host` must reach the generated config, for every engine.

The host used to be patched in with one regex requiring `host = "..."` to sit
immediately after `[engine.<name>]`. That made the template's layout
load-bearing, and when it did not match the requested host was dropped
silently.
"""

from __future__ import annotations

import pytest
import tomllib

from openjarvis.core.config import HardwareInfo, generate_default_toml


def _host_of(toml_text: str, engine: str) -> str:
    return tomllib.loads(toml_text)["engine"][engine]["host"]


class TestGeneratedConfig:
    @pytest.mark.parametrize(
        "engine,host",
        [
            ("ollama", "http://remote:11434"),
            ("vllm", "http://gpu-box:8000"),
            # Engines whose section is commented out or absent in the template
            # silently kept localhost before.
            ("nexa", "http://remote:9999"),
        ],
    )
    def test_requested_host_is_used(self, engine, host):
        toml_text = generate_default_toml(HardwareInfo(), engine, host=host)
        assert _host_of(toml_text, engine) == host

    def test_output_is_always_parseable(self):
        toml_text = generate_default_toml(HardwareInfo(), "ollama", host="http://x:1")
        tomllib.loads(toml_text)  # must not raise

    def test_no_host_leaves_the_template_alone(self):
        toml_text = generate_default_toml(HardwareInfo(), "ollama")
        assert _host_of(toml_text, "ollama") == "http://localhost:11434"


class TestHostileValues:
    """The host is data, not a regex replacement or a raw TOML fragment."""

    def test_backslash_does_not_raise(self):
        # Interpolated into a re.sub replacement this raised
        # "PatternError: invalid group reference 1".
        host = r"http://a\g<1>b"
        toml_text = generate_default_toml(HardwareInfo(), "ollama", host=host)
        assert _host_of(toml_text, "ollama") == host

    def test_quote_is_escaped(self):
        host = 'http://x"y'
        toml_text = generate_default_toml(HardwareInfo(), "ollama", host=host)
        assert _host_of(toml_text, "ollama") == host


class TestSetTomlHost:
    """The section editor itself, including the layouts the regex could not."""

    @staticmethod
    def _set_host(*args):
        from openjarvis.core.config import _set_toml_host

        return _set_toml_host(*args)

    def test_replaces_an_existing_key(self):
        out = self._set_host('[engine.ollama]\nhost = "old"\n', "ollama", "new")
        assert _host_of(out, "ollama") == "new"

    def test_tolerates_comments_between_header_and_key(self):
        """The regex required strict adjacency; a comment broke it silently."""
        src = '[engine.ollama]\n# a note\n\nhost = "old"\n'
        assert _host_of(self._set_host(src, "ollama", "new"), "ollama") == "new"

    def test_inserts_when_the_section_has_no_host(self):
        src = '[engine.ollama]\n# only comments here\n\n[engine.vllm]\nhost = "v"\n'
        out = self._set_host(src, "ollama", "new")
        assert _host_of(out, "ollama") == "new"
        # The neighbouring section must be untouched.
        assert _host_of(out, "vllm") == "v"

    def test_appends_when_the_section_is_missing(self):
        out = self._set_host('[engine.vllm]\nhost = "v"\n', "ollama", "new")
        assert _host_of(out, "ollama") == "new"
        assert _host_of(out, "vllm") == "v"

    def test_only_the_named_engine_changes(self):
        src = '[engine.ollama]\nhost = "a"\n\n[engine.vllm]\nhost = "b"\n'
        out = self._set_host(src, "vllm", "changed")
        assert _host_of(out, "ollama") == "a"
        assert _host_of(out, "vllm") == "changed"

    def test_commented_host_key_is_not_mistaken_for_the_real_one(self):
        src = '[engine.ollama]\n# host = "commented"\n'
        out = self._set_host(src, "ollama", "new")
        assert _host_of(out, "ollama") == "new"

    def test_trailing_newline_is_preserved(self):
        assert self._set_host('[engine.ollama]\nhost = "a"\n', "ollama", "b").endswith(
            "\n"
        )

"""Static guards for the docs-site savings-leaderboard Supabase wiring.

`docs/javascripts/leaderboard.js` reads the public Supabase anon key from
`window.OPENJARVIS_SUPABASE_ANON_KEY`. That global is set by a generated
config file (`leaderboard-config.js`) which must load *before* leaderboard.js,
and whose value is injected at docs-build time from the VITE_SUPABASE_ANON_KEY
secret (see `.github/workflows/docs.yml`). These are text-only checks — no
mkdocs build required — so they run in the default CI lane.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MKDOCS = ROOT / "mkdocs.yml"
DOCS_WORKFLOW = ROOT / ".github" / "workflows" / "docs.yml"
CONFIG_JS = ROOT / "docs" / "javascripts" / "leaderboard-config.js"
LEADERBOARD_JS = ROOT / "docs" / "javascripts" / "leaderboard.js"

_ANON_GLOBAL = "window.OPENJARVIS_SUPABASE_ANON_KEY"


def test_config_js_declares_anon_key_global():
    assert CONFIG_JS.is_file(), "leaderboard-config.js is missing"
    assert _ANON_GLOBAL in CONFIG_JS.read_text()


def test_leaderboard_reads_the_anon_key_global():
    # leaderboard.js must consume the global the config file sets.
    assert _ANON_GLOBAL in LEADERBOARD_JS.read_text()


def test_config_is_loaded_before_leaderboard_in_mkdocs():
    content = MKDOCS.read_text()
    cfg = content.index("javascripts/leaderboard-config.js")
    lb = content.index("javascripts/leaderboard.js")
    assert cfg < lb, "leaderboard-config.js must be listed before leaderboard.js"


def test_docs_workflow_injects_the_anon_key():
    content = DOCS_WORKFLOW.read_text()
    assert "VITE_SUPABASE_ANON_KEY" in content, "workflow doesn't read the secret"
    assert "leaderboard-config.js" in content, "workflow doesn't write the config file"
    assert _ANON_GLOBAL in content, "workflow doesn't set the anon-key global"

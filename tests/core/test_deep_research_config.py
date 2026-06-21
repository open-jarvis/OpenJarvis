from openjarvis.core.config import JarvisConfig, validate_config_key


def test_deep_research_defaults_are_empty():
    cfg = JarvisConfig()
    assert cfg.deep_research.engine == ""
    assert cfg.deep_research.model == ""


def test_deep_research_keys_are_settable():
    # _SETTABLE_SECTIONS is derived from JarvisConfig fields, so a new section
    # must be config-set-able without any extra registration.
    assert validate_config_key("deep_research.engine") is str
    assert validate_config_key("deep_research.model") is str

"""Tests for skill security — capability validation and trust tiers."""

from __future__ import annotations

from openjarvis.skills.security import (
    TrustTier,
    classify_trust_tier,
    has_dangerous_capabilities,
    validate_capabilities,
)
from openjarvis.skills.types import SkillManifest


class TestTrustTiers:
    def test_bundled_tier(self):
        assert classify_trust_tier(is_bundled=True) == TrustTier.BUNDLED

    def test_indexed_tier(self):
        assert (
            classify_trust_tier(has_signature=True, in_index=True) == TrustTier.INDEXED
        )

    def test_unreviewed_tier(self):
        assert (
            classify_trust_tier(has_signature=False, in_index=False)
            == TrustTier.UNREVIEWED
        )

    def test_workspace_tier(self):
        assert classify_trust_tier(is_workspace=True) == TrustTier.WORKSPACE


class TestCapabilityValidation:
    def test_valid_capabilities(self):
        manifest = SkillManifest(name="test", required_capabilities=["network:fetch"])
        allowed = {"network:fetch", "filesystem:read"}
        assert validate_capabilities(manifest, allowed) == []

    def test_missing_capability(self):
        manifest = SkillManifest(name="test", required_capabilities=["shell:execute"])
        allowed = {"network:fetch"}
        violations = validate_capabilities(manifest, allowed)
        assert "shell:execute" in violations


class TestDangerousCapabilities:
    def test_detects_dangerous(self):
        manifest = SkillManifest(
            name="test", required_capabilities=["shell:execute", "network:fetch"]
        )
        dangerous = has_dangerous_capabilities(manifest)
        assert "shell:execute" in dangerous
        assert "network:fetch" not in dangerous

    def test_no_dangerous(self):
        manifest = SkillManifest(
            name="test", required_capabilities=["network:fetch", "filesystem:read"]
        )
        assert has_dangerous_capabilities(manifest) == []

"""Tests for Ed25519 signing (Phase 14.6)."""

from __future__ import annotations

import pytest


def _skip_if_no_cryptography():
    try:
        import cryptography  # noqa: F401
    except ImportError:
        pytest.skip("cryptography not installed")


class TestSigning:
    def test_generate_keypair(self):
        _skip_if_no_cryptography()
        from openjarvis.security.signing import generate_keypair

        kp = generate_keypair()
        assert len(kp.private_key) == 32
        assert len(kp.public_key) == 32

    def test_sign_and_verify(self):
        _skip_if_no_cryptography()
        from openjarvis.security.signing import generate_keypair, sign, verify

        kp = generate_keypair()
        data = b"hello world"
        sig = sign(data, kp.private_key)
        assert len(sig) == 64
        assert verify(data, sig, kp.public_key)

    def test_verify_wrong_data(self):
        _skip_if_no_cryptography()
        from openjarvis.security.signing import generate_keypair, sign, verify

        kp = generate_keypair()
        sig = sign(b"hello", kp.private_key)
        assert not verify(b"wrong", sig, kp.public_key)

    def test_verify_wrong_key(self):
        _skip_if_no_cryptography()
        from openjarvis.security.signing import generate_keypair, sign, verify

        kp1 = generate_keypair()
        kp2 = generate_keypair()
        sig = sign(b"data", kp1.private_key)
        assert not verify(b"data", sig, kp2.public_key)

    def test_sign_b64(self):
        _skip_if_no_cryptography()
        from openjarvis.security.signing import generate_keypair, sign_b64, verify_b64

        kp = generate_keypair()
        data = b"test data"
        sig_b64 = sign_b64(data, kp.private_key)
        assert isinstance(sig_b64, str)
        assert verify_b64(data, sig_b64, kp.public_key)

    def test_verify_b64_invalid(self):
        _skip_if_no_cryptography()
        from openjarvis.security.signing import generate_keypair, verify_b64

        kp = generate_keypair()
        assert not verify_b64(b"data", "invalid-base64!!!", kp.public_key)

    def test_save_and_load_keypair(self, tmp_path):
        _skip_if_no_cryptography()
        from openjarvis.security.signing import (
            generate_keypair,
            load_public_key,
            save_keypair,
            sign,
            verify,
        )

        kp = generate_keypair()
        priv_path = str(tmp_path / "private.key")
        pub_path = str(tmp_path / "public.key")
        save_keypair(kp, priv_path, pub_path)

        loaded_pub = load_public_key(pub_path)
        assert len(loaded_pub) == 32

        sig = sign(b"test", kp.private_key)
        assert verify(b"test", sig, loaded_pub)

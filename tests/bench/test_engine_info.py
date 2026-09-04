"""Tests for ``engine_info`` — run metadata from self-describing engines.

Benchmark results are written to JSONL, so whatever ``describe()`` returns
has to survive ``json.dumps``. It does not come from a trusted source: it is
duck-typed off whatever object the caller passed as the engine.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from openjarvis.bench._stubs import engine_info


class _Described:
    def __init__(self, payload):
        self._payload = payload

    def describe(self):
        return self._payload


def test_returns_none_when_engine_cannot_describe_itself():
    engine = object()
    assert engine_info(engine) is None


def test_returns_the_described_payload():
    info = engine_info(
        _Described(
            {
                "engine_id": "afm",
                "afm_context_size": 4096,
                "afm_instructions": None,
            }
        )
    )
    assert info == {
        "engine_id": "afm",
        "afm_context_size": 4096,
        "afm_instructions": None,
    }


def test_mock_engine_does_not_poison_the_jsonl_write():
    """A MagicMock answers ``describe()`` with another MagicMock.

    Passing that straight into benchmark metadata made the whole run fail with
    "Object of type MagicMock is not JSON serializable" at write time -- which
    is exactly the shape of an engine returning something unexpected.
    """
    engine = MagicMock()
    assert engine_info(engine) is None


def test_non_dict_payloads_are_rejected():
    assert engine_info(_Described("just a string")) is None
    assert engine_info(_Described(None)) is None


def test_describe_that_raises_is_not_fatal():
    class _Broken:
        def describe(self):
            raise RuntimeError("host query failed")

    assert engine_info(_Broken()) is None


def test_unserializable_values_are_stringified_not_dropped():
    info = engine_info(_Described({"engine_id": "afm", "handle": object()}))
    assert info["engine_id"] == "afm"
    assert isinstance(info["handle"], str)
    # The whole point: the result must round-trip through JSON.
    json.dumps(info)


def test_result_is_always_json_serializable():
    payload = {
        "engine_id": "afm",
        "nested": {"a": [1, 2, 3]},
        "bad": MagicMock(),
        7: "non-string key is dropped",
    }
    info = engine_info(_Described(payload))
    json.dumps(info)
    assert 7 not in info
    assert info["nested"] == {"a": [1, 2, 3]}

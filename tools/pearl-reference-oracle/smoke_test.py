"""Pearl mining smoke test — runs an end-to-end mine + verify cycle.

Verifies that this host can run Pearl's pure-Rust mining algorithm via the
`pearl_mining` Python package. Used as Phase 0-B of the OpenJarvis Apple Silicon
mining spec ([Spec B]).

Exit codes:
    0   all checks passed
    1   pearl_mining import failed
    2   mine() failed
    3   verify_plain_proof rejected the proof
    4   timing or sanity check failed

[Spec B]: ../../docs/design/2026-05-05-apple-silicon-pearl-mining-design.md
"""

from __future__ import annotations

import platform
import sys
import time

# Test fixture values — match upstream Pearl's tests/test_python_api.py so we are
# testing the same code path that Pearl's own CI exercises. Do not change
# without re-syncing with upstream.
DEFAULT_NBITS = 0x1D2FFFFF
DEFAULT_M = 256
DEFAULT_N = 128
DEFAULT_K = 1024
DEFAULT_RANK = 32
ROWS_PATTERN = [0, 8, 64, 72]
COLS_PATTERN = [0, 1, 8, 9, 32, 33, 40, 41]


def _ok(msg: str) -> None:
    print(f"[ok] {msg}")


def _fail(msg: str, code: int) -> None:
    print(f"[fail] {msg}")
    sys.exit(code)


def main() -> None:
    print(f"host: {platform.platform()} ({platform.machine()})")
    print(f"python: {sys.version.split()[0]}")

    try:
        import pearl_mining
    except ImportError as e:
        _fail(f"could not import pearl_mining — install with `uv pip install py-pearl-mining` or build from source: {e}", 1)

    _ok(f"pearl_mining loaded from {pearl_mining.__file__}")
    _ok(
        f"PUBLICDATA_SIZE={pearl_mining.PUBLICDATA_SIZE}  "
        f"MERKLE_LEAF_SIZE={pearl_mining.MERKLE_LEAF_SIZE}"
    )

    block_header = pearl_mining.IncompleteBlockHeader(
        version=0,
        prev_block=b"\x00" * 32,
        merkle_root=b"0123456789abcdef" * 2,
        timestamp=0x66666666,
        nbits=DEFAULT_NBITS,
    )
    mining_config = pearl_mining.MiningConfiguration(
        common_dim=DEFAULT_K,
        rank=DEFAULT_RANK,
        mma_type=pearl_mining.MMAType.Int7xInt7ToInt32,
        rows_pattern=pearl_mining.PeriodicPattern.from_list(ROWS_PATTERN),
        cols_pattern=pearl_mining.PeriodicPattern.from_list(COLS_PATTERN),
        reserved=pearl_mining.MiningConfiguration.RESERVED,
    )

    t0 = time.perf_counter()
    try:
        plain_proof = pearl_mining.mine(
            DEFAULT_M,
            DEFAULT_N,
            DEFAULT_K,
            block_header,
            mining_config,
            signal_range=None,
            wrong_jackpot_hash=False,
        )
    except Exception as e:
        _fail(f"mine() raised: {e!r}", 2)
    t_mine = time.perf_counter() - t0

    _ok(
        f"mine(m={DEFAULT_M}, n={DEFAULT_N}, k={DEFAULT_K}, rank={DEFAULT_RANK}) "
        f"returned a proof in {t_mine:.3f} s"
    )
    print(
        f"       proof.m={plain_proof.m} proof.n={plain_proof.n} proof.k={plain_proof.k}  "
        f"noise_rank={plain_proof.noise_rank}"
    )
    print(
        f"       a.row_indices={plain_proof.a.row_indices}  "
        f"bt.row_indices={plain_proof.bt.row_indices}"
    )

    t0 = time.perf_counter()
    ok, msg = pearl_mining.verify_plain_proof(block_header, plain_proof)
    t_verify_ms = (time.perf_counter() - t0) * 1000

    if not ok:
        _fail(f"verify_plain_proof rejected our proof: {msg}", 3)

    _ok(f"verify_plain_proof: ok=True ({msg!r}, {t_verify_ms:.1f} ms)")

    if plain_proof.m != DEFAULT_M or plain_proof.n != DEFAULT_N or plain_proof.k != DEFAULT_K:
        _fail("plain_proof dimensions do not match request", 4)
    if plain_proof.noise_rank != DEFAULT_RANK:
        _fail("plain_proof noise_rank does not match request", 4)

    # Row indices are (offset + base_index) for some valid offset within the
    # matrix dimension — see threads_partition() in zk-pow/src/ffi/mine.rs.
    # We can't assert an absolute value (different offsets are valid every run),
    # but we can assert the deltas match the pattern shape.
    a_idxs = list(plain_proof.a.row_indices)
    bt_idxs = list(plain_proof.bt.row_indices)
    a_deltas = [v - a_idxs[0] for v in a_idxs]
    bt_deltas = [v - bt_idxs[0] for v in bt_idxs]
    if a_deltas != ROWS_PATTERN:
        _fail(f"a.row_indices deltas ({a_deltas}) != ROWS_PATTERN ({ROWS_PATTERN})", 4)
    if bt_deltas != COLS_PATTERN:
        _fail(f"bt.row_indices deltas ({bt_deltas}) != COLS_PATTERN ({COLS_PATTERN})", 4)

    print()
    print("[ok] all checks passed — Pearl mining works on this host")
    print()
    print("Note: this used test difficulty (nbits=0x1D2FFFFF), not mainnet.")
    print("Real-network shares per second will be many orders of magnitude lower.")
    print("See docs/design/2026-05-05-apple-silicon-pearl-mining-design.md §1.5.6")


if __name__ == "__main__":
    main()

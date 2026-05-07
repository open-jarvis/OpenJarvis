"""CPU mining-loop subprocess entry point.

Run with::

    python -m openjarvis.mining._miner_loop_main \
        --gateway-host 127.0.0.1 --gateway-port 8337 \
        --m 256 --n 128 --k 1024 --rank 32

Connects to pearl-gateway, polls for work via ``getMiningInfo``, runs
``pearl_mining.mine()``, submits proofs via ``submitPlainProof``. Designed
to be killed via SIGTERM by the parent provider; no graceful shutdown
handshake -- Pearl's gateway tolerates client disconnects cleanly.

The parent OJ process spawns this module via ``python -m`` and never
imports it directly, keeping the parent's import graph free of
``pearl_mining`` (which is an optional dependency installed only with
``--extra mining-pearl-cpu``).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
from typing import Any

logger = logging.getLogger("openjarvis.mining.miner_loop")

# Backoff after a failed mining round before retrying. Short enough that
# transient gateway errors don't stall mining; long enough not to spin.
_FAILURE_BACKOFF_SECONDS = 1.0
_CONNECT_RETRY_SECONDS = 0.25
_CONNECT_TIMEOUT_SECONDS = 30.0


def _make_request(
    method: str, params: dict[str, Any], request_id: int
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request envelope matching gateway's schema."""
    return {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}


def _decode_mining_info(result: dict[str, Any]) -> tuple[bytes, int]:
    """Decode a getMiningInfo result into ``(incomplete_header_bytes, target)``."""
    header_b64 = result["incomplete_header_bytes"]
    target = int(result["target"])
    return base64.b64decode(header_b64), target


def _encode_plain_proof(plain_proof: Any) -> str:
    """Return the proof as a base64 string for ``submitPlainProof``.

    Pearl's ``PlainProof`` exposes ``to_base64()`` directly — no manual
    encoding required. (Verified via py-pearl-mining 0.1.0 on macOS arm64.)
    """
    return plain_proof.to_base64()


async def _read_response(reader: asyncio.StreamReader) -> dict[str, Any]:
    """Read one line of JSON-RPC response from the gateway socket."""
    line = await reader.readline()
    if not line:
        raise ConnectionError("gateway closed the connection")
    return json.loads(line)


async def _send_request(writer: asyncio.StreamWriter, request: dict[str, Any]) -> None:
    """Write one JSON-RPC request followed by newline."""
    writer.write(json.dumps(request).encode() + b"\n")
    await writer.drain()


async def _open_gateway_connection(
    host: str,
    port: int,
    *,
    timeout_seconds: float = _CONNECT_TIMEOUT_SECONDS,
    retry_seconds: float = _CONNECT_RETRY_SECONDS,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to pearl-gateway, retrying while its listener comes up."""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_error: OSError | None = None
    while True:
        try:
            return await asyncio.open_connection(host, port)
        except OSError as exc:
            last_error = exc
            if asyncio.get_running_loop().time() >= deadline:
                raise ConnectionError(
                    f"timed out connecting to pearl-gateway at {host}:{port}"
                ) from last_error
            logger.info(
                "gateway %s:%d not ready yet (%s); retrying",
                host,
                port,
                exc,
            )
            await asyncio.sleep(retry_seconds)


def _build_mining_config(pearl_mining_module: Any, *, k: int, rank: int) -> Any:
    """Build the upstream MiningConfiguration with default patterns."""
    from ._constants import (
        CPU_PEARL_DEFAULT_COLS_PATTERN,
        CPU_PEARL_DEFAULT_ROWS_PATTERN,
    )

    return pearl_mining_module.MiningConfiguration(
        common_dim=k,
        rank=rank,
        mma_type=pearl_mining_module.MMAType.Int7xInt7ToInt32,
        rows_pattern=pearl_mining_module.PeriodicPattern.from_list(
            list(CPU_PEARL_DEFAULT_ROWS_PATTERN)
        ),
        cols_pattern=pearl_mining_module.PeriodicPattern.from_list(
            list(CPU_PEARL_DEFAULT_COLS_PATTERN)
        ),
        reserved=pearl_mining_module.MiningConfiguration.RESERVED,
    )


async def _mine_one_round(
    pearl_mining_module: Any,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    request_id: int,
    m: int,
    n: int,
    k: int,
    rank: int,
) -> bool:
    """Get work, mine, submit. Return True if the gateway accepted the proof."""
    # 1. Ask the gateway for work.
    await _send_request(writer, _make_request("getMiningInfo", {}, request_id))
    info_response = await _read_response(reader)
    if "error" in info_response:
        logger.warning("getMiningInfo error: %s", info_response["error"])
        return False
    header_bytes, target = _decode_mining_info(info_response["result"])

    # 2. Reconstruct the IncompleteBlockHeader and run pearl_mining.mine().
    # Verified APIs (py-pearl-mining 0.1.0 on macOS arm64):
    #   - IncompleteBlockHeader.from_bytes(bytes) -> IncompleteBlockHeader
    #   - PlainProof.to_base64() -> str  (used by _encode_plain_proof above)
    header = pearl_mining_module.IncompleteBlockHeader.from_bytes(header_bytes)
    mining_config = _build_mining_config(pearl_mining_module, k=k, rank=rank)
    plain_proof = pearl_mining_module.mine(
        m, n, k, header, mining_config, signal_range=None, wrong_jackpot_hash=False
    )

    # 3. Submit the proof back to the gateway.
    submit_params = {
        "plain_proof": _encode_plain_proof(plain_proof),
        "mining_job": {
            "incomplete_header_bytes": base64.b64encode(header_bytes).decode(),
            "target": target,
        },
    }
    await _send_request(
        writer, _make_request("submitPlainProof", submit_params, request_id + 1)
    )
    submit_response = await _read_response(reader)
    if "error" in submit_response:
        logger.warning("submitPlainProof rejected: %s", submit_response["error"])
        return False
    return True


async def _main_loop(args: argparse.Namespace) -> None:
    import pearl_mining  # imported lazily so this module is itself import-safe

    reader, writer = await _open_gateway_connection(
        args.gateway_host,
        args.gateway_port,
        timeout_seconds=args.connect_timeout_seconds,
        retry_seconds=args.connect_retry_seconds,
    )
    request_id = 0
    try:
        while True:
            request_id += 2
            try:
                accepted = await _mine_one_round(
                    pearl_mining,
                    reader,
                    writer,
                    request_id=request_id,
                    m=args.m,
                    n=args.n,
                    k=args.k,
                    rank=args.rank,
                )
            except Exception:
                logger.exception("mining round failed; retrying after backoff")
                await asyncio.sleep(_FAILURE_BACKOFF_SECONDS)
                continue
            if accepted:
                logger.info("share accepted")
            else:
                await asyncio.sleep(_FAILURE_BACKOFF_SECONDS)
    finally:
        writer.close()
        await writer.wait_closed()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="openjarvis.mining._miner_loop_main")
    p.add_argument("--gateway-host", default="127.0.0.1")
    p.add_argument("--gateway-port", type=int, default=8337)
    p.add_argument("--m", type=int, default=256)
    p.add_argument("--n", type=int, default=128)
    p.add_argument("--k", type=int, default=1024)
    p.add_argument("--rank", type=int, default=32)
    p.add_argument("--connect-timeout-seconds", type=float, default=30.0)
    p.add_argument("--connect-retry-seconds", type=float, default=0.25)
    return p.parse_args(argv)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = parse_args()
    try:
        asyncio.run(_main_loop(args))
    except KeyboardInterrupt:
        sys.exit(0)

"""A/B retrieval benchmark: local HybridSearch vs Mixedbread (toast-1).

Runs the Deep Research retrieval arms over a BrowseComp-Plus subset
(prepared as JSON: {"queries": [...], "docs": {docid: {text, url}}})
and reports evidence recall, MRR, and latency per arm:

  hybrid  — local BM25 + vector RRF (BM25-only if Ollama is down)
  mxbai   — Mixedbread managed search, agentic=False
  toast1  — Mixedbread agentic search (toast-1)

The corpus is windowed into ~3.5KB chunks and indexed identically on
both sides (chunks mirrored via MixedbreadKnowledgeSync), so the arms
differ only in retrieval — the thing being measured. (SemanticChunker
is deliberately not used here: line-heavy wiki-style corpus docs make
its structural splitting emit tens of thousands of tiny chunks.)

Usage:
  uv run python scripts/bench_retrieval_ab.py subset.json \
      [--arms hybrid,mxbai,toast1] [--store-name NAME] [--skip-sync] \
      [--queries N] [--limit 20] [--delete-store] [--out results.json]

Requires MXBAI_API_KEY for the mxbai/toast1 arms. Sends corpus content
and queries to the Mixedbread cloud API.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from typing import Any, Dict, List

from openjarvis.connectors.embeddings import OllamaEmbedder
from openjarvis.connectors.hybrid_search import HybridSearch
from openjarvis.connectors.mixedbread_search import (
    MixedbreadKnowledgeSync,
    MixedbreadSearch,
)
from openjarvis.connectors.store import KnowledgeStore


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def window_chunks(text: str, size: int = 3500, overlap: int = 300) -> List[str]:
    """Fixed-size windows with overlap, breaking at whitespace when possible."""
    out: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            ws = text.rfind(" ", start + size // 2, end)
            if ws > start:
                end = ws
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def build_local_index(subset: Dict[str, Any]) -> tuple[KnowledgeStore, bool]:
    """Chunk + index every subset doc; embed when Ollama is available."""
    store = KnowledgeStore(db_path=":memory:")
    embedder = OllamaEmbedder()
    embeddings_on = embedder.is_available()
    if not embeddings_on:
        log("WARNING: Ollama embedder unavailable — hybrid arm is BM25-only")

    n_chunks = 0
    n_embedded = 0
    t0 = time.perf_counter()
    for docid, doc in subset["docs"].items():
        for idx, content in enumerate(window_chunks(doc["text"])):
            vec = embedder.embed(content) if embeddings_on else None
            if vec is None and embeddings_on:
                vec = embedder.embed(content)  # one retry for transient 500s
            store.store(
                content=content,
                source="bcp",
                doc_id=docid,
                url=doc.get("url") or "",
                chunk_index=idx,
                embedding=vec,
                embedding_model_version=embedder.model_version if vec else "",
            )
            n_chunks += 1
            n_embedded += vec is not None
    emb = f"{n_embedded}/{n_chunks}" if embeddings_on else "off"
    log(
        f"indexed {len(subset['docs'])} docs -> {n_chunks} chunks in "
        f"{time.perf_counter() - t0:.0f}s (embedded: {emb})"
    )
    if embeddings_on and n_embedded < n_chunks * 0.95:
        log("WARNING: embedding coverage below 95% — vector leg is degraded")
    return store, embeddings_on


def wait_for_indexing(client: Any, store_id: str, timeout: float = 900.0) -> None:
    """Poll the store until no files are pending/in-progress."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = client.stores.retrieve(store_id)
        counts = getattr(info, "file_counts", None) or getattr(info, "counts", None)
        if counts is None:
            log("store exposes no file counts; settling 60s instead")
            time.sleep(60)
            return
        pending = (getattr(counts, "pending", 0) or 0) + (
            getattr(counts, "in_progress", 0) or 0
        )
        if pending == 0:
            return
        log(f"  indexing... {pending} file(s) pending")
        time.sleep(10)
    log("WARNING: indexing wait timed out; proceeding anyway")


def doc_ranking(hits: List[Any]) -> List[str]:
    """Chunk hits -> unique doc ids, preserving rank order."""
    seen: List[str] = []
    for h in hits:
        if h.document_id not in seen:
            seen.append(h.document_id)
    return seen


def evaluate_arm(
    name: str,
    search: Any,
    queries: List[Dict[str, Any]],
    indexed: set,
    *,
    limit: int,
) -> Dict[str, Any]:
    per_query: List[Dict[str, Any]] = []
    for q in queries:
        evidence = [d for d in q["evidence"] if d in indexed]
        if not evidence:
            continue
        t0 = time.perf_counter()
        try:
            hits = search.search(q["query"], limit=limit)
            error = ""
        except Exception as exc:  # noqa: BLE001
            hits, error = [], f"{type(exc).__name__}: {exc}"
        latency = time.perf_counter() - t0

        docs = doc_ranking(hits)
        top10 = docs[:10]
        found10 = [d for d in evidence if d in top10]
        gold = [d for d in q["gold"] if d in indexed]
        first_rank = next((i + 1 for i, d in enumerate(top10) if d in evidence), None)
        snippets = " ".join(h.content_snippet.lower() for h in hits[:10])
        per_query.append(
            {
                "qid": q["qid"],
                "recall@10": len(found10) / len(evidence),
                "recall@20": len([d for d in evidence if d in docs[:20]])
                / len(evidence),
                "gold_hit@10": (any(d in top10 for d in gold) if gold else None),
                "mrr@10": (1.0 / first_rank) if first_rank else 0.0,
                "answer_in_snippets": (
                    q["answer"].lower() in snippets if q["answer"] else None
                ),
                "latency_s": latency,
                "error": error,
            }
        )
        log(
            f"  [{name}] {q['qid']}: recall@10="
            f"{per_query[-1]['recall@10']:.2f} ({latency:.1f}s)"
            + (f" ERROR {error}" if error else "")
        )

    def mean(key: str) -> float:
        vals = [p[key] for p in per_query if p[key] is not None]
        return sum(vals) / len(vals) if vals else 0.0

    lats = [p["latency_s"] for p in per_query]
    gold_vals = [p["gold_hit@10"] for p in per_query if p["gold_hit@10"] is not None]
    ans_vals = [
        p["answer_in_snippets"]
        for p in per_query
        if p["answer_in_snippets"] is not None
    ]
    return {
        "arm": name,
        "n": len(per_query),
        "recall@10": mean("recall@10"),
        "recall@20": mean("recall@20"),
        "mrr@10": mean("mrr@10"),
        "gold_hit@10": (sum(gold_vals) / len(gold_vals)) if gold_vals else None,
        "answer_in_snippets": (sum(ans_vals) / len(ans_vals)) if ans_vals else None,
        "latency_p50": statistics.median(lats) if lats else 0.0,
        "latency_p95": (
            sorted(lats)[max(0, int(len(lats) * 0.95) - 1)] if lats else 0.0
        ),
        "errors": sum(1 for p in per_query if p["error"]),
        "per_query": per_query,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subset", help="Path to the prepared subset JSON")
    ap.add_argument("--arms", default="hybrid,mxbai,toast1")
    ap.add_argument("--store-name", default="openjarvis-bcp-bench")
    ap.add_argument(
        "--skip-sync",
        action="store_true",
        help="Reuse an already-synced Mixedbread store",
    )
    ap.add_argument("--queries", type=int, default=0, help="Cap query count")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--delete-store", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    with open(args.subset) as fh:
        subset = json.load(fh)
    queries = subset["queries"][: args.queries] if args.queries else subset["queries"]
    indexed = set(subset["docs"])
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    log(f"{len(queries)} queries, {len(indexed)} docs, arms={arms}")

    store, embeddings_on = build_local_index(subset)

    needs_cloud = {"mxbai", "toast1"} & set(arms)
    mx_kwargs = dict(store_name=args.store_name)
    if needs_cloud and not args.skip_sync:
        sync = MixedbreadKnowledgeSync(store, max_workers=16, **mx_kwargs)
        t0 = time.perf_counter()
        report = sync.sync()
        log(
            f"synced {report.uploaded}/{report.total} chunks in "
            f"{time.perf_counter() - t0:.0f}s ({report.failed} failed)"
        )
        probe = MixedbreadSearch(store, **mx_kwargs)
        wait_for_indexing(probe._client, probe._ensure_store())

    results = []
    for arm in arms:
        log(f"--- arm: {arm} ---")
        if arm == "hybrid":
            embedder = OllamaEmbedder() if embeddings_on else None
            search: Any = HybridSearch(store, embedder)
        elif arm == "mxbai":
            search = MixedbreadSearch(store, agentic=False, **mx_kwargs)
        elif arm == "toast1":
            search = MixedbreadSearch(store, agentic=True, **mx_kwargs)
        else:
            log(f"unknown arm {arm!r}, skipping")
            continue
        results.append(evaluate_arm(arm, search, queries, indexed, limit=args.limit))

    header = (
        f"{'arm':<8} {'n':>3} {'recall@10':>9} {'recall@20':>9} {'mrr@10':>7} "
        f"{'gold@10':>8} {'ans@10':>7} {'p50 lat':>8} {'p95 lat':>8} {'err':>4}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        gold = f"{r['gold_hit@10']:.2f}" if r["gold_hit@10"] is not None else "  — "
        ans = (
            f"{r['answer_in_snippets']:.2f}"
            if r["answer_in_snippets"] is not None
            else "  — "
        )
        print(
            f"{r['arm']:<8} {r['n']:>3} {r['recall@10']:>9.3f} "
            f"{r['recall@20']:>9.3f} {r['mrr@10']:>7.3f} {gold:>8} {ans:>7} "
            f"{r['latency_p50']:>7.2f}s {r['latency_p95']:>7.2f}s {r['errors']:>4}"
        )
    if not embeddings_on and "hybrid" in arms:
        print("note: hybrid ran BM25-only (Ollama embedder unavailable)")

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(results, fh, indent=2)
        log(f"wrote {args.out}")

    if args.delete_store and needs_cloud:
        probe = MixedbreadSearch(store, **mx_kwargs)
        probe._client.stores.delete(args.store_name)
        log(f"deleted store '{args.store_name}'")
    elif needs_cloud:
        log(
            f"store '{args.store_name}' kept (re-run with --skip-sync, or "
            f"clean up with --delete-store)"
        )


if __name__ == "__main__":
    main()

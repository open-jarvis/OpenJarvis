"""Tests for the DenseMemory backend.

These tests exercise retrieval quality on a small fixture corpus, then
assert on the actual cosine-similarity score distribution the embedding
model produces. The thresholds here are set **empirically** from the
observed scores on nomic-embed-text — not guessed upfront — so a
regression in either the embedder or the chunker will show up as a
failing assertion rather than a silently bad result.

The tests require Ollama with ``nomic-embed-text`` pulled; they are
skipped if the server is unreachable.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from openjarvis.tools.storage.dense import (
    DenseMemory,
    MdChunk,
    chunk_markdown,
    dedupe_chunks,
)
from openjarvis.tools.storage.embeddings import OllamaEmbedder

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "docs"
_EMBED_MODEL = "nomic-embed-text"


def _ollama_base_url() -> str:
    """Resolve the Ollama base URL from ``OLLAMA_HOST``.

    The project documents ``OLLAMA_HOST`` as a full URL
    (``http://<remote-ip>:11434``), but Ollama's own convention also
    allows bare ``host`` / ``host:port`` forms — accept all three so
    the probe and the embedder under test agree on one endpoint.
    """
    host = os.environ.get("OLLAMA_HOST", "")
    if not host:
        return "http://localhost:11434"
    if host.startswith(("http://", "https://")):
        return host.rstrip("/")
    if ":" in host:
        return f"http://{host}"
    return f"http://{host}:11434"


def _ollama_up() -> bool:
    """True only if Ollama is reachable *and* the embed model is pulled.

    A bare TCP connect isn't enough — a machine can run Ollama for chat
    models without ever having pulled ``nomic-embed-text``, which makes
    ``/api/embed`` 404 instead of the tests skipping as intended.
    """
    try:
        resp = httpx.get(f"{_ollama_base_url()}/api/tags", timeout=1.0)
        resp.raise_for_status()
        models = {m.get("model", "") for m in resp.json().get("models", [])}
        return any(m.startswith(_EMBED_MODEL) for m in models)
    except (httpx.HTTPError, ValueError):
        return False


def _make_backend() -> DenseMemory:
    """DenseMemory wired to the same Ollama endpoint the probe checked.

    ``DenseMemory()`` alone would build an ``OllamaEmbedder`` with its
    hard-coded localhost default, so a remote ``OLLAMA_HOST`` could pass
    the probe and then have every test call the wrong server.
    """
    return DenseMemory(
        embedder=OllamaEmbedder(model=_EMBED_MODEL, base_url=_ollama_base_url())
    )


ollama_required = pytest.mark.skipif(
    not _ollama_up(),
    reason=(
        "Requires Ollama with nomic-embed-text "
        "(start `ollama serve` then `ollama pull nomic-embed-text`)"
    ),
)


# ---------------------------------------------------------------------------
# Skip-guard unit tests (no Ollama required)
# ---------------------------------------------------------------------------


class _FakeTagsResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class TestOllamaProbe:
    def test_base_url_accepts_all_documented_forms(self, monkeypatch):
        cases = {
            "http://remote:11434": "http://remote:11434",
            "http://remote:11434/": "http://remote:11434",
            "https://ollama.internal": "https://ollama.internal",
            "remote:8080": "http://remote:8080",
            "remote": "http://remote:11434",
        }
        for raw, expected in cases.items():
            monkeypatch.setenv("OLLAMA_HOST", raw)
            assert _ollama_base_url() == expected, raw
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        assert _ollama_base_url() == "http://localhost:11434"

    def test_probe_false_when_server_down(self, monkeypatch):
        def _refuse(url, timeout):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "get", _refuse)
        assert _ollama_up() is False

    def test_probe_false_when_model_missing(self, monkeypatch):
        monkeypatch.setattr(
            httpx,
            "get",
            lambda url, timeout: _FakeTagsResponse({"models": [{"model": "llama3"}]}),
        )
        assert _ollama_up() is False

    def test_probe_true_with_tagged_model_on_configured_url(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "http://remote:9999")
        seen = {}

        def _get(url, timeout):
            seen["url"] = url
            return _FakeTagsResponse({"models": [{"model": "nomic-embed-text:latest"}]})

        monkeypatch.setattr(httpx, "get", _get)
        assert _ollama_up() is True
        assert seen["url"] == "http://remote:9999/api/tags"


# ---------------------------------------------------------------------------
# Chunking unit tests (no Ollama required)
# ---------------------------------------------------------------------------


class TestChunkMarkdown:
    def test_empty_text(self):
        assert chunk_markdown("") == []
        assert chunk_markdown("   \n\n  ") == []

    def test_single_section_without_splits(self):
        md = (
            "# Title\n\nSome body paragraph with a few sentences. Enough to be a chunk."
        )
        chunks = chunk_markdown(md, source="t.md")
        assert len(chunks) == 1
        assert chunks[0].breadcrumb == "Title"
        assert "body paragraph" in chunks[0].content

    def test_splits_on_h2_and_h3(self):
        md = (
            "# Book\n\n"
            "## Chapter One\n\nfirst body.\n\n"
            "### Section A\n\nalpha body.\n\n"
            "### Section B\n\nbeta body.\n\n"
            "## Chapter Two\n\ngamma body.\n"
        )
        chunks = chunk_markdown(md, source="t.md")
        breadcrumbs = [c.breadcrumb for c in chunks]
        # Every header change becomes a new chunk
        assert "Book > Chapter One" in breadcrumbs
        assert "Book > Chapter One > Section A" in breadcrumbs
        assert "Book > Chapter One > Section B" in breadcrumbs
        assert "Book > Chapter Two" in breadcrumbs

    def test_ignores_headers_inside_code_fences(self):
        # Inside a fenced code block, lines starting with '#' are
        # shell/python comments, not markdown headers.
        md = (
            "# Guide\n\n"
            "## Install\n\n"
            "Run these commands:\n\n"
            "```bash\n"
            "# Install Homebrew\n"
            "# Build the Rust extension\n"
            "brew install rust\n"
            "```\n\n"
            "Then verify.\n"
        )
        chunks = chunk_markdown(md, source="t.md")
        breadcrumbs = [c.breadcrumb for c in chunks]
        assert "Guide > Install" in breadcrumbs
        # Must NOT have parsed the shell comments as headers:
        assert not any("Install Homebrew" in b for b in breadcrumbs)
        assert not any("Build the Rust extension" in b for b in breadcrumbs)

    def test_oversize_section_is_split_with_overlap(self):
        body = " ".join(["word"] * 2500)
        md = f"# Big\n\n## Section\n\n{body}\n"
        chunks = chunk_markdown(
            md,
            source="t.md",
            max_section_tokens=500,
            paragraph_overlap_tokens=50,
        )
        assert len(chunks) >= 2
        for c in chunks:
            # Every chunk carries the breadcrumb
            assert c.breadcrumb == "Big > Section"


# ---------------------------------------------------------------------------
# Cross-file deduplication (no Ollama required)
# ---------------------------------------------------------------------------


def _mk(content: str, source: str) -> MdChunk:
    return MdChunk(content=f"Header\n\n{content}", source=source, breadcrumb="Header")


class TestDedupeChunks:
    def test_no_dedupe_when_under_threshold_files(self):
        """Two identical chunks across two files should NOT be deduped (need 3+)."""
        chunks = [
            _mk("the quick brown fox jumps over the lazy dog every morning", "a.md"),
            _mk("the quick brown fox jumps over the lazy dog every morning", "b.md"),
        ]
        survivors, report = dedupe_chunks(chunks, min_files_for_dup=3)
        assert len(survivors) == 2
        assert report.removed_count == 0

    def test_dedupes_boilerplate_across_three_files(self):
        """Same blurb in 3+ files → keep one canonical, drop the rest."""
        body = "openjarvis runs entirely on your hardware no cloud needed local first"
        chunks = [
            _mk(body, "docs/index.md"),
            _mk(body, "docs/downloads.md"),
            _mk(body, "docs/getting-started/installation.md"),
        ]
        survivors, report = dedupe_chunks(chunks, min_files_for_dup=3)
        assert len(survivors) == 1
        # Most-specific source path wins (deepest)
        assert survivors[0].source == "docs/getting-started/installation.md"
        assert report.removed_count == 2
        assert len(report.groups) == 1
        grp = report.groups[0]
        assert grp.distinct_files == 3
        assert "docs/index.md" in grp.dropped_sources
        assert "docs/downloads.md" in grp.dropped_sources

    def test_keeps_distinct_content(self):
        """Genuinely different chunks must survive even with shared phrases."""
        chunks = [
            _mk(
                "install ollama with brew install ollama then run ollama serve",
                "a.md",
            ),
            _mk(
                "configure vllm with tensor parallelism and prefix caching",
                "b.md",
            ),
            _mk(
                "llama.cpp builds with cmake and supports cpu metal cuda rocm",
                "c.md",
            ),
        ]
        survivors, report = dedupe_chunks(chunks)
        assert len(survivors) == 3
        assert report.removed_count == 0

    def test_minor_edit_is_clustered_when_body_is_long_enough(self):
        """A one-word swap in a long boilerplate paragraph still clusters.

        At 5-grams a one-word change kills 5 n-grams; in a short 14-word
        sentence that's half the grams (Jaccard ~0.33 — below the 0.7
        threshold), but in real boilerplate paragraphs the change is a
        small fraction of total grams and the cluster still forms. This
        test uses a paragraph long enough to put Jaccard above 0.7.
        """
        common = (
            "openjarvis is a personal ai platform that runs entirely on your "
            "own hardware no cloud apis required by default the project is "
            "open source apache 2 licensed and supports ollama vllm sglang "
            "and llama cpp inference engines with auto detection of your "
            "available compute resources at startup so the right backend is "
            "picked without manual configuration in most cases"
        )
        # One-word change shouldn't break clustering on this length
        a = common + " choose the interface that suits you"
        b = common + " pick the interface that suits you"
        c = common + " select the interface that suits you"
        chunks = [_mk(a, "a.md"), _mk(b, "b.md"), _mk(c, "c.md")]
        survivors, report = dedupe_chunks(chunks)
        assert len(survivors) == 1, (
            f"got {len(survivors)} survivors — expected single cluster from boilerplate"
        )
        assert report.removed_count == 2

    def test_breadcrumb_difference_does_not_block_dedupe(self):
        """Identical body wrapped in different breadcrumbs still dedupes.

        Without stripping the breadcrumb prefix before n-gram extraction,
        chunks with the same body but different leading words (e.g.
        ``Downloads`` vs ``Installation``) would have lower Jaccard.
        """
        body = (
            "openjarvis runs entirely on your hardware no cloud needed "
            "local first foundation"
        )
        chunks = [
            MdChunk(
                content=f"Downloads\n\n{body}",
                source="docs/downloads.md",
                breadcrumb="Downloads",
            ),
            MdChunk(
                content=f"Installation\n\n{body}",
                source="docs/install.md",
                breadcrumb="Installation",
            ),
            MdChunk(
                content=f"Welcome\n\n{body}",
                source="docs/index.md",
                breadcrumb="Welcome",
            ),
        ]
        survivors, report = dedupe_chunks(chunks, min_files_for_dup=3)
        assert len(survivors) == 1, (
            f"got {len(survivors)} survivors: {[s.source for s in survivors]}"
        )
        assert report.removed_count == 2

    def test_path_specificity_tiebreaker(self):
        """When duplicates exist, the deepest path wins."""
        body = (
            "we use the orchestrator agent backed by tools and memory "
            "backends configured per recipe"
        )
        chunks = [
            _mk(body, "shallow.md"),
            _mk(body, "docs/middle.md"),
            _mk(body, "docs/getting-started/installation.md"),
        ]
        survivors, _ = dedupe_chunks(chunks, min_files_for_dup=3)
        assert len(survivors) == 1
        assert survivors[0].source == "docs/getting-started/installation.md"

    def test_empty_input(self):
        survivors, report = dedupe_chunks([])
        assert survivors == []
        assert report.input_count == 0
        assert report.output_count == 0

    def test_does_not_remove_more_than_corpus(self):
        """Sanity: removed_count <= input_count, output_count >= 1 per cluster."""
        body = "boilerplate about how openjarvis runs entirely on your hardware locally"
        chunks = [_mk(body, f"f{i}.md") for i in range(10)]
        survivors, report = dedupe_chunks(chunks, min_files_for_dup=3)
        # 10 files all duplicates → 1 survives
        assert len(survivors) == 1
        assert report.removed_count == 9
        assert report.output_count + report.removed_count == report.input_count


# ---------------------------------------------------------------------------
# Retrieval quality tests (require Ollama + nomic-embed-text)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def indexed_backend():
    """DenseMemory populated from the fixture corpus once per module."""
    if not _ollama_up():
        pytest.skip("Ollama not reachable")

    backend = _make_backend()
    md_files = sorted(_FIXTURE_DIR.glob("*.md"))
    assert md_files, f"no fixtures at {_FIXTURE_DIR}"

    contents, sources, metadatas = [], [], []
    for f in md_files:
        for chunk in chunk_markdown(f.read_text(encoding="utf-8"), source=f.name):
            contents.append(chunk.content)
            sources.append(chunk.source)
            metadatas.append({"breadcrumb": chunk.breadcrumb})
    backend.store_many(contents, sources=sources, metadatas=metadatas)
    return backend


@ollama_required
def test_index_built_with_expected_chunk_count(indexed_backend):
    # 4 fixture files with small sections should give a modest chunk count —
    # not 1 (indexing broken), not 100 (splitting gone wild).
    n = indexed_backend.count()
    assert 8 <= n <= 25, f"unexpected chunk count: {n}"


# Threshold chosen empirically from the score distribution documented in
# test_score_distribution_vs_threshold below. See twitter_bot.py for the
# shared constant used at runtime.
_SCORE_THRESHOLD = 0.55


@ollama_required
def test_exact_match_is_top_hit(indexed_backend):
    """A query lifted verbatim from the corpus should return that chunk at rank 1.

    We avoid generic terms like "backends" (which match both memory.md
    and engines.md) and use a phrase that's distinctive in one doc.
    """
    results = indexed_backend.retrieve("BM25 and FAISS for memory retrieval", top_k=3)
    assert results, "expected at least one hit"
    assert results[0].source == "memory.md"
    assert "bm25" in results[0].content.lower() or "faiss" in results[0].content.lower()
    # Verbatim-ish matches against nomic-embed-text cluster around 0.7+
    assert results[0].score > 0.65, f"top score too low: {results[0].score}"


@ollama_required
def test_paraphrase_matches_semantically(indexed_backend):
    """A paraphrase of doc content should still retrieve an on-topic chunk.

    Note: for the "can I run this on a laptop without a gpu?" case the
    top hit is ``engines.md > llama.cpp`` (not ``hardware.md > Running
    Without a GPU``) because the llama.cpp section explicitly says
    "ideal for laptops without a discrete GPU" — a near-literal match
    for the query. That's fine for grounding: both chunks contain the
    facts we need (CPU-only, llama.cpp).
    """
    results = indexed_backend.retrieve(
        "can I run this on a laptop without a gpu?",
        top_k=3,
    )
    assert results, "expected at least one hit"
    # Top-3 should all be from the topical docs (engines.md or hardware.md)
    topical = {r.source for r in results[:3]}
    assert topical <= {"engines.md", "hardware.md"}, (
        f"off-topic sources in top-3: {topical}"
    )
    top_lc = results[0].content.lower()
    assert "llama.cpp" in top_lc or "cpu" in top_lc


@ollama_required
def test_engine_query_finds_engines_doc(indexed_backend):
    """Semantic query about inference engines should find engines.md."""
    results = indexed_backend.retrieve(
        "which backend is best for high throughput serving?",
        top_k=3,
    )
    assert results
    assert results[0].source == "engines.md"
    assert results[0].score > 0.65


@ollama_required
def test_off_topic_query_scores_below_threshold(indexed_backend):
    """Clearly off-topic queries must fall below the router's threshold.

    This is the property the Twitter bot depends on: when the user asks
    something unrelated to the docs, retrieval must score below
    ``_SCORE_THRESHOLD`` so the bot chooses the deferral path instead of
    grounding on nonsense.

    Note: ``nomic-embed-text`` inflates off-topic scores (observed
    up to ~0.51 on this corpus) — a plain sentence-transformer would
    give a wider gap, but we're optimizing for the in-process embedder
    we actually have.
    """
    off_topic_queries = [
        "how do I bake a chocolate chip cookie",
        "what is the capital of Mongolia",
        "recommend me a pop song",
        "why is the sky blue",
    ]
    for q in off_topic_queries:
        hits = indexed_backend.retrieve(q, top_k=1)
        assert hits, f"expected any hit for {q!r}"
        assert hits[0].score < _SCORE_THRESHOLD, (
            f"off-topic query {q!r} scored {hits[0].score:.3f} — above "
            f"threshold {_SCORE_THRESHOLD}, would trigger a false-positive "
            f"ground. Tune threshold up or expand corpus."
        )


@ollama_required
def test_score_distribution_vs_threshold(indexed_backend, capsys):
    """Document the observed score distribution so the threshold is audit-able.

    We do NOT assert ``rel_min > off_max`` — nomic-embed-text produces
    overlapping ranges on small narrow corpora. Instead we verify that
    the chosen threshold cleanly separates the two *medians*, which is
    the property we actually rely on at the router: **most** relevant
    queries ground and **all** off-topic queries defer.
    """
    relevant_queries = [
        "BM25 FAISS Hybrid backends",
        "can I run this on a laptop without a gpu?",
        "which backend is best for high throughput serving?",
        "how do I add a new channel integration",
        "what happens when i store conflicting facts?",
    ]
    off_topic_queries = [
        "how do I bake a chocolate chip cookie",
        "what is the capital of Mongolia",
        "recommend me a pop song",
        "why is the sky blue",
    ]

    def _top1(q: str) -> float:
        hits = indexed_backend.retrieve(q, top_k=1)
        return hits[0].score

    rel = sorted(_top1(q) for q in relevant_queries)
    off = sorted(_top1(q) for q in off_topic_queries)

    rel_median = rel[len(rel) // 2]
    off_median = off[len(off) // 2]

    print(f"\n  relevant scores:   {[round(s, 3) for s in rel]}")
    print(f"  off-topic scores:  {[round(s, 3) for s in off]}")
    print(f"  relevant median:   {rel_median:.3f}")
    print(f"  off-topic median:  {off_median:.3f}")
    print(f"  chosen threshold:  {_SCORE_THRESHOLD}")

    # Medians must be cleanly separated by the threshold
    assert rel_median > _SCORE_THRESHOLD, (
        f"relevant median {rel_median:.3f} <= threshold {_SCORE_THRESHOLD} — "
        f"too many relevant queries will be deferred."
    )
    assert off_median < _SCORE_THRESHOLD, (
        f"off-topic median {off_median:.3f} >= threshold {_SCORE_THRESHOLD} — "
        f"too many nonsense queries will ground."
    )


# ---------------------------------------------------------------------------
# API-level sanity
# ---------------------------------------------------------------------------


class TestDenseMemoryAPI:
    @ollama_required
    def test_store_and_delete(self):
        backend = _make_backend()
        doc_id = backend.store("the cat sat on the mat", source="a.txt")
        assert backend.count() == 1
        hits = backend.retrieve("where is the cat", top_k=1)
        assert hits and hits[0].metadata["doc_id"] == doc_id
        assert backend.delete(doc_id)
        assert backend.count() == 0
        assert not backend.delete(doc_id)

    @ollama_required
    def test_empty_retrieve(self):
        backend = _make_backend()
        assert backend.retrieve("anything", top_k=3) == []

    @ollama_required
    def test_clear(self):
        backend = _make_backend()
        backend.store("foo")
        backend.store("bar")
        backend.clear()
        assert backend.count() == 0
        assert backend.retrieve("foo", top_k=1) == []

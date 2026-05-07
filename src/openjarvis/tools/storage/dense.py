"""In-memory dense retrieval backend.

Uses any :class:`Embedder` (default: :class:`OllamaEmbedder` with
``nomic-embed-text``) to embed stored text, then ranks queries by
cosine similarity via a single matrix multiply against an
L2-normalized matrix of document embeddings.

Design notes
------------
* **No persistence.** The index lives in memory and is rebuilt at
  startup via :mod:`scripts.index_docs`. The docs corpus is small
  (~700 chunks) so this is fine and keeps the implementation simple.
* **Normalization happens at embed time**, not at query time. Storing
  unit vectors means retrieval is one ``docs @ query`` dot product.
* **Store growth is amortized**: we keep a list of per-call embedding
  matrices and concatenate lazily in :meth:`retrieve`. This avoids an
  O(n²) ``np.concatenate`` pattern while still giving callers one
  contiguous matrix when they actually need to search.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult
from openjarvis.tools.storage.embeddings import Embedder, OllamaEmbedder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Markdown-aware chunking
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(r"^```")
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(slots=True)
class MdChunk:
    """A markdown chunk annotated with its header breadcrumb."""

    content: str           # chunk body text (with breadcrumb prefix)
    source: str            # originating file
    # e.g. "macOS Installation Guide > Step-by-Step > Step 6 — Install llama.cpp"
    breadcrumb: str
    start_line: int = 0


def _iter_nonfenced_lines(text: str):
    """Yield ``(line_number, line_text, in_code)`` for each line.

    ``in_code`` is True for lines inside a ```...``` fenced block, so
    callers can ignore shell/python comments that start with ``#``.
    """
    in_code = False
    for lineno, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if _FENCE_RE.match(stripped):
            in_code = not in_code
            yield lineno, line, True  # the fence itself is "code"
            continue
        yield lineno, line, in_code


def chunk_markdown(
    text: str,
    *,
    source: str = "",
    max_section_tokens: int = 500,
    paragraph_overlap_tokens: int = 50,
    max_section_chars: int = 4000,
) -> List[MdChunk]:
    """Split markdown into chunks using ``##``/``###`` as primary boundaries.

    Strategy:
      1. Detect section boundaries at h2 (``##``) and h3 (``###``).
         h1 (``#``) is treated as the document title (captured in the
         breadcrumb but not used to split).
      2. Skip headers that appear inside fenced code blocks — those are
         usually shell comments (``# Install X``) not real headers.
      3. If a section body exceeds ``max_section_tokens`` (whitespace
         tokens) OR ``max_section_chars`` (raw chars), slide a window
         over its paragraphs with ``paragraph_overlap_tokens`` overlap.
      4. Prefix each chunk with a ``breadcrumb`` of its parent headers
         so the embedding captures hierarchical context.

    The char cap is the critical safety net: embedding models count BPE
    tokens, and technical content (file paths, code, URLs) has ~8 BPE
    tokens per whitespace token — so a whitespace-token-only limit
    silently lets 2–3× overflows through and some embedders (e.g.
    ``nomic-embed-text``) reject them at runtime. 4000 chars is a
    conservative ceiling for ``nomic-embed-text``'s 8192-token window.

    Empty input → empty list.
    """
    if not text or not text.strip():
        return []

    # Pass 1: parse into (h1, h2, h3, body_lines) sections
    h1: Optional[str] = None
    h2: Optional[str] = None
    h3: Optional[str] = None
    buffered: List[str] = []
    # Each entry: (breadcrumb, body_text, start_line)
    sections: List[tuple[str, str, int]] = []
    section_start_line = 0

    def _flush(start_line: int):
        nonlocal buffered
        if not buffered:
            return
        body = "\n".join(buffered).strip()
        if not body:
            buffered = []
            return
        parts = [p for p in (h1, h2, h3) if p]
        breadcrumb = " > ".join(parts) if parts else (source or "(unnamed)")
        sections.append((breadcrumb, body, start_line))
        buffered = []

    for lineno, line, in_code in _iter_nonfenced_lines(text):
        if in_code:
            buffered.append(line)
            continue
        m = _HEADER_RE.match(line.strip())
        if m is None:
            buffered.append(line)
            continue
        hashes, title = m.group(1), m.group(2).strip()
        level = len(hashes)
        if level == 1:
            # Document title — flush whatever we had, then set h1
            _flush(section_start_line)
            h1 = title
            h2 = None
            h3 = None
            section_start_line = lineno
        elif level == 2:
            _flush(section_start_line)
            h2 = title
            h3 = None
            section_start_line = lineno
        elif level == 3:
            _flush(section_start_line)
            h3 = title
            section_start_line = lineno
        else:
            # h4+ stays inline in the body
            buffered.append(line)
    _flush(section_start_line)

    if not sections:
        # Doc had no ## / ### splits at all; fall back to treating the
        # whole thing as one section.
        parts = [p for p in (h1,) if p]
        breadcrumb = " > ".join(parts) if parts else (source or "(unnamed)")
        sections = [(breadcrumb, text.strip(), 0)]

    # Pass 2: for each section, split if it's too large (token or char).
    chunks: List[MdChunk] = []

    def _over_limit(tok_count: int, char_count: int) -> bool:
        return tok_count > max_section_tokens or char_count > max_section_chars

    for breadcrumb, body, start_line in sections:
        body_tokens = body.split()
        if not _over_limit(len(body_tokens), len(body)):
            chunks.append(
                MdChunk(
                    content=f"{breadcrumb}\n\n{body}",
                    source=source,
                    breadcrumb=breadcrumb,
                    start_line=start_line,
                )
            )
            continue

        # Oversized — slide over paragraphs, with a token-level fallback
        # for single paragraphs that are themselves larger than the window.
        paragraphs = [p for p in body.split("\n\n") if p.strip()]
        window_paragraphs: List[str] = []
        window_tokens = 0
        window_chars = 0

        def _emit_window():
            nonlocal window_paragraphs, window_tokens, window_chars
            if not window_paragraphs:
                return
            chunk_body = "\n\n".join(window_paragraphs).strip()
            chunks.append(
                MdChunk(
                    content=f"{breadcrumb}\n\n{chunk_body}",
                    source=source,
                    breadcrumb=breadcrumb,
                    start_line=start_line,
                )
            )
            # Carry overlap tail into the next window
            tail = " ".join(chunk_body.split()[-paragraph_overlap_tokens:]) \
                if paragraph_overlap_tokens > 0 else ""
            window_paragraphs = [tail] if tail else []
            window_tokens = len(tail.split())
            window_chars = len(tail)

        for para in paragraphs:
            p_tokens = para.split()

            # Single paragraph too big for the window: flush what we
            # have, then slide a fixed token window over it.
            if _over_limit(len(p_tokens), len(para)):
                _emit_window()
                # Use whichever cap is tighter for this paragraph —
                # if it's char-bound, slide by chars; else by tokens.
                char_bound = (
                    len(para) > max_section_chars
                    and len(p_tokens) <= max_section_tokens
                )
                if char_bound:
                    step_chars = max(
                        1, max_section_chars - (paragraph_overlap_tokens * 8),
                    )
                    for i in range(0, len(para), step_chars):
                        piece = para[i : i + max_section_chars]
                        chunks.append(
                            MdChunk(
                                content=f"{breadcrumb}\n\n{piece}",
                                source=source,
                                breadcrumb=breadcrumb,
                                start_line=start_line,
                            )
                        )
                        if i + max_section_chars >= len(para):
                            break
                else:
                    step = max(1, max_section_tokens - paragraph_overlap_tokens)
                    for i in range(0, len(p_tokens), step):
                        window_content = " ".join(
                            p_tokens[i : i + max_section_tokens]
                        )
                        # Safety: truncate if still over char cap
                        if len(window_content) > max_section_chars:
                            window_content = window_content[:max_section_chars]
                        chunks.append(
                            MdChunk(
                                content=f"{breadcrumb}\n\n{window_content}",
                                source=source,
                                breadcrumb=breadcrumb,
                                start_line=start_line,
                            )
                        )
                        if i + max_section_tokens >= len(p_tokens):
                            break
                window_paragraphs = []
                window_tokens = 0
                window_chars = 0
                continue

            # Would adding this paragraph push us over either limit?
            sep = 2 if window_paragraphs else 0  # for the "\n\n" between paras
            if (
                _over_limit(
                    window_tokens + len(p_tokens),
                    window_chars + len(para) + sep,
                )
                and window_paragraphs
            ):
                _emit_window()
            window_paragraphs.append(para)
            window_tokens += len(p_tokens)
            window_chars += len(para) + (2 if len(window_paragraphs) > 1 else 0)

        _emit_window()

    return chunks


# ---------------------------------------------------------------------------
# Cross-file deduplication
# ---------------------------------------------------------------------------


_NORM_WS_RE = re.compile(r"\s+")
_NORM_NONALPHA_RE = re.compile(r"[^a-z0-9\s]+")


@dataclass(slots=True)
class DuplicateGroup:
    """A cluster of chunks judged to be near-duplicates of each other."""

    kept_index: int                   # surviving chunk's index in the input list
    kept_source: str
    dropped_indices: List[int] = field(default_factory=list)
    dropped_sources: List[str] = field(default_factory=list)
    distinct_files: int = 0           # # of unique source files in the group
    sample_text: str = ""             # ~120-char preview of the duplicated content


@dataclass(slots=True)
class DedupeReport:
    """Audit trail for a deduplication pass."""

    input_count: int = 0
    output_count: int = 0
    groups: List[DuplicateGroup] = field(default_factory=list)

    @property
    def removed_count(self) -> int:
        return self.input_count - self.output_count

    @property
    def removed_fraction(self) -> float:
        return self.removed_count / self.input_count if self.input_count else 0.0


def _strip_breadcrumb(content: str) -> str:
    """Drop the breadcrumb prefix produced by chunk_markdown.

    The breadcrumb varies between files even for boilerplate body text
    (Downloads vs Installation, etc.), which would suppress similarity
    if included in the n-gram set. Compare body-only.
    """
    parts = content.split("\n\n", 1)
    return parts[1] if len(parts) == 2 else content


def _normalize(text: str) -> str:
    """Lowercase, drop non-alphanumeric, collapse whitespace."""
    text = text.lower()
    text = _NORM_NONALPHA_RE.sub(" ", text)
    text = _NORM_WS_RE.sub(" ", text)
    return text.strip()


def _ngrams(text: str, n: int = 5) -> set:
    """Word-level n-gram set."""
    tokens = text.split()
    if len(tokens) < n:
        # Short chunks: use the whole token tuple as a single n-gram so
        # very-short identical chunks still cluster.
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


class _UnionFind:
    """Tiny union-find for clustering near-duplicate chunks."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _path_specificity(source: str) -> Tuple[int, int, str]:
    """Sort key — bigger is more specific.

    Tiebreakers:
      1. Path depth (slashes) — deeper = more specific.
      2. Length of basename — proxy for descriptiveness.
      3. Lexicographic source path — deterministic last-resort.
    """
    if not source:
        return (-1, 0, "")
    depth = source.count("/")
    basename = source.rsplit("/", 1)[-1]
    return (depth, len(basename), source)


def dedupe_chunks(
    chunks: List[MdChunk],
    *,
    ngram_n: int = 5,
    similarity_threshold: float = 0.7,
    min_files_for_dup: int = 3,
) -> Tuple[List[MdChunk], DedupeReport]:
    """Drop near-duplicate chunks that recur across many source files.

    A chunk cluster is considered a duplicate (and collapsed to one
    canonical entry) when:

      1. Pairwise word-level n-gram **Jaccard >= ``similarity_threshold``**
         on the body text (breadcrumb stripped). N-grams are computed
         after lowercasing and stripping non-alphanumeric punctuation,
         so superficial differences (capitalization, typography) don't
         hide duplication.
      2. The cluster spans **>= ``min_files_for_dup`` distinct source
         files**. Two-file repeats are kept on the assumption they may
         be legitimately doc-specific; >=3 is the bar for boilerplate.

    For each qualifying cluster, the chunk from the most-specific
    source path wins (deepest dir, longest basename, lexicographic
    tiebreak); the rest are dropped.

    Returns ``(surviving_chunks, report)``. The chunker, embedder and
    retrieval logic are NOT modified — this function is a pure pre-
    processing pass over the chunk list before embedding.
    """
    n = len(chunks)
    if n == 0:
        return [], DedupeReport()

    # 1) Compute n-gram set for each chunk (body only)
    chunk_ngrams: List[set] = []
    for c in chunks:
        body = _strip_breadcrumb(c.content)
        chunk_ngrams.append(_ngrams(_normalize(body), n=ngram_n))

    # 2) Inverted index: ngram -> [chunk indices that contain it]
    # Lets us skip pairs that share zero n-grams without computing Jaccard.
    inverted: Dict[tuple, List[int]] = defaultdict(list)
    for i, ngs in enumerate(chunk_ngrams):
        for ng in ngs:
            inverted[ng].append(i)

    # 3) Build candidate-pair set: any pair sharing at least one n-gram.
    #    For each n-gram, at most ``cap`` chunks contribute to candidate
    #    pairs to avoid quadratic blowup on hyper-common n-grams (e.g.
    #    ``("the", "the", ...)``-style noise — unlikely but defensive).
    cap = 200
    candidate_pairs: set = set()
    for chunk_ids in inverted.values():
        if len(chunk_ids) < 2:
            continue
        if len(chunk_ids) > cap:
            chunk_ids = chunk_ids[:cap]
        for i_idx in range(len(chunk_ids)):
            for j_idx in range(i_idx + 1, len(chunk_ids)):
                a, b = chunk_ids[i_idx], chunk_ids[j_idx]
                if a > b:
                    a, b = b, a
                candidate_pairs.add((a, b))

    # 4) Cluster via union-find on pairs that exceed the threshold.
    uf = _UnionFind(n)
    for a, b in candidate_pairs:
        if _jaccard(chunk_ngrams[a], chunk_ngrams[b]) >= similarity_threshold:
            uf.union(a, b)

    # 5) Group by cluster root
    cluster_to_members: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        cluster_to_members[uf.find(i)].append(i)

    # 6) For each cluster, decide: dedupe or keep all?
    keep_mask = [True] * n
    report = DedupeReport(input_count=n)
    for members in cluster_to_members.values():
        if len(members) < 2:
            continue
        distinct_files = {chunks[i].source for i in members}
        if len(distinct_files) < min_files_for_dup:
            continue  # not boilerplate enough — keep all

        # Pick canonical: most-specific source path
        sorted_members = sorted(
            members,
            key=lambda i: _path_specificity(chunks[i].source),
            reverse=True,
        )
        kept_idx = sorted_members[0]
        dropped_idxs = sorted_members[1:]
        for d in dropped_idxs:
            keep_mask[d] = False

        sample = _strip_breadcrumb(chunks[kept_idx].content).strip().replace("\n", " ")
        report.groups.append(
            DuplicateGroup(
                kept_index=kept_idx,
                kept_source=chunks[kept_idx].source,
                dropped_indices=dropped_idxs,
                dropped_sources=[chunks[i].source for i in dropped_idxs],
                distinct_files=len(distinct_files),
                sample_text=sample[:120] + ("..." if len(sample) > 120 else ""),
            )
        )

    survivors = [c for i, c in enumerate(chunks) if keep_mask[i]]
    report.output_count = len(survivors)
    return survivors, report


def log_dedupe_report(report: DedupeReport, *, level: int = logging.INFO) -> None:
    """Emit a human-readable summary of a dedupe pass at ``level``."""
    pct = report.removed_fraction * 100
    logger.log(
        level,
        "dedupe: %d -> %d chunks (%d removed, %.1f%%) across %d clusters",
        report.input_count,
        report.output_count,
        report.removed_count,
        pct,
        len(report.groups),
    )
    for grp in report.groups:
        logger.log(
            level,
            "  kept %s  dropped %d (across %d files): %s | %r",
            grp.kept_source,
            len(grp.dropped_indices),
            grp.distinct_files,
            ", ".join(sorted(set(grp.dropped_sources))),
            grp.sample_text,
        )


# ---------------------------------------------------------------------------
# DenseMemory backend
# ---------------------------------------------------------------------------


@MemoryRegistry.register("dense")
class DenseMemory(MemoryBackend):
    """In-memory dense retrieval via cosine similarity.

    The embedder is lazy: it is created on first :meth:`store` or
    :meth:`retrieve` call, so instantiating :class:`DenseMemory` does
    not require Ollama to be running.

    Parameters
    ----------
    embedder:
        An :class:`Embedder` instance.  If ``None``, defaults to
        :class:`OllamaEmbedder` with ``nomic-embed-text``.
    """

    backend_id = "dense"

    def __init__(self, embedder: Optional[Embedder] = None) -> None:
        self._embedder: Optional[Embedder] = embedder
        # Shape (n_docs, dim), L2-normalized row-wise. None until first store.
        self._matrix = None
        self._contents: List[str] = []
        self._sources: List[str] = []
        self._metadatas: List[Dict[str, Any]] = []
        self._doc_ids: List[str] = []
        # id -> index; lets us delete in O(1) for lookups
        self._id_to_index: Dict[str, int] = {}
        self._lock = threading.Lock()

    # -- embedder lifecycle ------------------------------------------------

    def _get_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = OllamaEmbedder()
        return self._embedder

    # -- MemoryBackend ABC -------------------------------------------------

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Embed and store one document. Returns its id."""
        return self.store_many(
            [content], sources=[source], metadatas=[metadata or {}],
        )[0]

    def store_many(
        self,
        contents: List[str],
        *,
        sources: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Embed a batch of documents in one go. Much faster than per-doc.

        Accepts parallel lists; missing sources/metadatas default to empty.
        """
        import numpy as np

        if not contents:
            return []
        sources = sources if sources is not None else [""] * len(contents)
        metadatas = metadatas if metadatas is not None else [{} for _ in contents]
        assert len(sources) == len(contents) and len(metadatas) == len(contents)

        emb = self._get_embedder()
        vectors = emb.embed(contents)  # already normalized
        new_ids = [uuid.uuid4().hex for _ in contents]

        with self._lock:
            if self._matrix is None:
                self._matrix = vectors
            else:
                self._matrix = np.concatenate([self._matrix, vectors], axis=0)
            for i, (c, s, m, doc_id) in enumerate(
                zip(contents, sources, metadatas, new_ids),
            ):
                self._contents.append(c)
                self._sources.append(s)
                self._metadatas.append(dict(m))
                self._doc_ids.append(doc_id)
                self._id_to_index[doc_id] = len(self._contents) - 1
        return new_ids

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Return top-k documents by cosine similarity.

        Scores are in ``[-1, 1]`` for normalized vectors; for
        nomic-embed-text in practice scores on reasonable queries
        fall in ``[0.3, 0.8]``. Empty index or query → empty list.
        """
        import numpy as np

        if not query or not query.strip():
            return []

        with self._lock:
            matrix_snapshot = self._matrix
            contents = list(self._contents)
            sources = list(self._sources)
            metadatas = [dict(m) for m in self._metadatas]
            doc_ids = list(self._doc_ids)

        if matrix_snapshot is None or matrix_snapshot.shape[0] == 0:
            return []

        emb = self._get_embedder()
        q_vec = emb.embed([query])  # shape (1, dim), normalized
        # Single matrix-vector mult
        scores = matrix_snapshot @ q_vec[0]  # shape (n,)

        # Top-k via argpartition then sort
        n = scores.shape[0]
        k = min(top_k, n)
        if k <= 0:
            return []
        if k < n:
            top_idx = np.argpartition(-scores, k - 1)[:k]
        else:
            top_idx = np.arange(n)
        # Sort the top-k chunk descending by score
        top_idx = top_idx[np.argsort(-scores[top_idx])]

        results: List[RetrievalResult] = []
        for i in top_idx:
            i = int(i)
            results.append(
                RetrievalResult(
                    content=contents[i],
                    score=float(scores[i]),
                    source=sources[i],
                    metadata={**metadatas[i], "doc_id": doc_ids[i]},
                )
            )
        return results

    def delete(self, doc_id: str) -> bool:
        """Remove a document by id. Returns True if it existed."""
        import numpy as np

        with self._lock:
            idx = self._id_to_index.pop(doc_id, None)
            if idx is None:
                return False
            # Remove row from matrix
            self._matrix = np.delete(self._matrix, idx, axis=0)
            self._contents.pop(idx)
            self._sources.pop(idx)
            self._metadatas.pop(idx)
            self._doc_ids.pop(idx)
            # Rebuild id -> index for entries after the removed one
            for did, i in list(self._id_to_index.items()):
                if i > idx:
                    self._id_to_index[did] = i - 1
        return True

    def clear(self) -> None:
        """Drop all stored documents."""
        with self._lock:
            self._matrix = None
            self._contents.clear()
            self._sources.clear()
            self._metadatas.clear()
            self._doc_ids.clear()
            self._id_to_index.clear()

    def count(self) -> int:
        """Number of stored documents."""
        with self._lock:
            return len(self._contents)


__all__ = [
    "DenseMemory",
    "DedupeReport",
    "DuplicateGroup",
    "MdChunk",
    "chunk_markdown",
    "dedupe_chunks",
    "log_dedupe_report",
]

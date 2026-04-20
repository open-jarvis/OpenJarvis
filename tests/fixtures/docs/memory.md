# Memory and Retrieval

OpenJarvis stores facts the agent has learned so it can retrieve them later.

## Backends

The default is SQLite with FTS5 for keyword search. BM25, FAISS (dense vector), and Hybrid (BM25 + dense) backends are also available.

## Conflicting Facts

When you store "X is true" today and "X is false" tomorrow, the memory system keeps both records with timestamps. Retrieval is recency-biased by default so the latest fact wins, but older versions remain queryable.

## Deleting Memories

Call `backend.delete(doc_id)` to remove a single record, or `backend.clear()` to wipe everything. There is currently no undo.

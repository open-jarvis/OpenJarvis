"""Model capability helpers shared by server model-selection routes."""

_EMBEDDING_MODEL_PREFIXES = (
    "all-minilm",
    "bge-",
    "bge_",
    "e5-",
    "e5_",
    "gte-",
    "gte_",
    "jina-embeddings",
    "nomic-bert",
    "sentence-transformers",
)


def is_embed_only_model(model_name: str) -> bool:
    """Return whether a model identifier denotes a non-chat embedder.

    Ollama does not expose capabilities through its model-list response, so
    model selection needs a conservative name-based guard.  Most embedding
    models contain ``embed``; the explicit prefixes cover common families
    such as MiniLM, BGE, E5, and GTE whose names do not.
    """
    name = (model_name or "").strip().lower()
    leaf = name.rsplit("/", 1)[-1].split(":", 1)[0]
    return (
        "embed" in leaf
        or "minilm" in leaf
        or leaf.startswith(_EMBEDDING_MODEL_PREFIXES)
    )


__all__ = ["is_embed_only_model"]

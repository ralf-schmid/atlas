"""Local embeddings for the lessons retrieval — see docs/features/F098.

ARCHITECTURE.md §3.3.1 / CLAUDE.md: **no local LLMs in the trading path, local
embeddings only** (bge-m3). This module is the whole "local" part of that rule.

`fastembed` rather than `sentence-transformers`: it runs the model through
onnxruntime instead of pulling torch, which keeps the image on a NAS-sized budget.

**Model deviates from CLAUDE.md — see ADR-0013.** CLAUDE.md names bge-m3;
fastembed does not offer it (`TextEmbedding.list_supported_models()` rejects it).
`intfloat/multilingual-e5-large` is the closest available substitute: same 1024
dimensions, same ~2.2 GB class, multilingual — which matters, because the lessons
being embedded are German and an English-only model would quietly degrade recall.

The model is downloaded on first use and cached under `EMBEDDING_CACHE_DIR`. That
path is a mounted volume in docker-compose; without it every container restart
re-downloads ~2 GB.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

#: bge-m3 output width. Fixed in the DB column, so changing the model means a
#: migration — not a config switch.
EMBEDDING_DIM = 1024
_MODEL_NAME = "intfloat/multilingual-e5-large"
_CACHE_DIR_ENV = "EMBEDDING_CACHE_DIR"


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...


class FastEmbedProvider:
    """Lazy: the model is loaded on first `embed`, not at import.

    Importing this module must stay free — it is pulled in by the scheduler, the
    API and the Telegram bot, and only one of them ever embeds anything. Loading
    ~2 GB of ONNX weights in every process would be pure waste.
    """

    def __init__(self, model_name: str = _MODEL_NAME) -> None:
        self._model_name = model_name
        self._model: object | None = None

    def _ensure_model(self) -> object:
        if self._model is None:
            from fastembed import TextEmbedding

            cache_dir = os.environ.get(_CACHE_DIR_ENV)
            logger.info(
                "loading embedding model", extra={"model": self._model_name, "cache": cache_dir}
            )
            self._model = TextEmbedding(
                model_name=self._model_name,
                cache_dir=str(Path(cache_dir)) if cache_dir else None,
            )
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._ensure_model()
        # e5 models are trained with an asymmetric "query:"/"passage:" prefix and
        # lose noticeable recall without it. Lessons and the situation we match them
        # against are both descriptive text, so both sides use "query:" — mixing the
        # two prefixes across a symmetric comparison is what actually hurts.
        vector = next(iter(model.embed([f"query: {text}"])))  # type: ignore[attr-defined]
        return [float(value) for value in vector]


def embed_lesson(provider: EmbeddingProvider, lessons_text: str | None) -> list[float] | None:
    """Returns None for an empty lesson rather than embedding the empty string.

    A zero-information vector would still be a nearest neighbour for something and
    would pollute retrieval with reviews that never said anything.
    """
    if lessons_text is None or not lessons_text.strip():
        return None
    return provider.embed(lessons_text.strip())

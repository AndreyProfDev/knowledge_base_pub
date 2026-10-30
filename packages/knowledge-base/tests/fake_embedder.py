"""A deterministic embedder: no server, no tokenizer download.

Each word hashes to a vector; a text is the normalised sum of its words', so texts
sharing words score closer. One token per word. Two instances with different
``vector_space`` / ``dimensions`` stand for two models.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence


def _word_vector(word: str, dimensions: int) -> list[float]:
    digest = hashlib.sha256(word.lower().encode()).digest()
    return [digest[i % len(digest)] / 127.5 - 1.0 for i in range(dimensions)]


class FakeEmbedder:
    def __init__(
        self,
        vector_space: str = "fake-8",
        dimensions: int = 8,
        max_input_tokens: int = 16,
        min_score: float | None = None,
    ) -> None:
        self.vector_space = vector_space
        self.dimensions = dimensions
        self.max_input_tokens = max_input_tokens
        self.min_score = min_score
        self.documents: list[str] = []
        """Every text ``embed_documents`` received, in order."""
        self.batch_sizes: list[int] = []
        """How many texts each ``embed_documents`` call received."""

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.documents.extend(texts)
        self.batch_sizes.append(len(texts))
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        total = [0.0] * self.dimensions
        for word in text.split() or [""]:
            total = [a + b for a, b in zip(total, _word_vector(word, self.dimensions), strict=True)]
        norm = math.sqrt(sum(x * x for x in total)) or 1.0
        return [x / norm for x in total]

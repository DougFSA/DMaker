"""BM25 (Okapi) sobre listas de termos: ranqueia documentos por uma consulta, sem biblioteca nem embeddings."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

K1 = 1.5  # quanto a repetição de um termo no mesmo trecho continua contando
B = 0.75  # quanto o tamanho do trecho desconta (trecho comprido casa mais palavras por acaso)


class Bm25:
    """Índice de documentos já divididos em termos; `scores` devolve a nota de cada um para uma consulta."""

    def __init__(self, documents: Sequence[Sequence[str]]) -> None:
        self._counts = [Counter(doc) for doc in documents]
        self._lengths = [len(doc) for doc in documents]
        total = len(documents)
        self._average = (sum(self._lengths) / total) if total else 0.0
        frequency: Counter[str] = Counter()
        for counts in self._counts:
            frequency.update(counts.keys())
        self._idf = {
            term: math.log((total - seen + 0.5) / (seen + 0.5) + 1.0) for term, seen in frequency.items()
        }

    def scores(self, query: Sequence[str]) -> list[float]:
        terms = [term for term in dict.fromkeys(query) if term in self._idf]
        out: list[float] = []
        for counts, length in zip(self._counts, self._lengths, strict=True):
            score = 0.0
            for term in terms:
                tf = counts.get(term, 0)
                if not tf:
                    continue
                norm = tf + K1 * (1 - B + B * length / (self._average or 1.0))
                score += self._idf[term] * tf * (K1 + 1) / norm
            out.append(score)
        return out

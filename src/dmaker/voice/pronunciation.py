"""Pronúncia: dicionário termo -> como falar e marcação pontual `[[termo|pronúncia]]` no roteiro.

Funções puras. O modelo de voz lê "DMaker" como "DeMaker"; em vez de pedir ao usuário que reescreva o
texto, o dicionário troca o termo por uma grafia que o modelo fala certo, só na hora de sintetizar. O
texto escrito (legendas, SRT) nunca muda.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

# `[[termo|pronúncia]]` fala só a pronúncia; `[[pronúncia]]` fala o conteúdo. O limite de 256 caracteres
# mantém a busca linear mesmo com colchetes soltos no texto (sem ele, `[[[[[[...` seria quadrático).
_INLINE_OVERRIDE = re.compile(r"\[\[([^\]]{0,256})\]\]")


DEFAULT_LANGUAGE = "pt"  # idioma dos termos escritos no formato antigo, sem escopo de idioma


def language_code(language: str) -> str:
    """`pt-BR`, `pt_br` e `PT` viram `pt`: a pronúncia vale por idioma, não por variante regional."""
    return re.split(r"[-_]", language.strip().lower())[0]


@dataclass(frozen=True)
class Lexicon:
    """Mapeamento termo -> pronúncia de um idioma, sem termos vazios nem duplicados que só diferem na caixa."""

    entries: tuple[tuple[str, str], ...] = ()

    @classmethod
    def of(cls, mapping: Mapping[str, str] | None = None) -> Lexicon:
        """Normaliza: apara espaços, descarta termo ou pronúncia vazios; o último termo repetido (sem diferenciar caixa) vence."""
        unique: dict[str, tuple[str, str]] = {}
        for term, spoken in (mapping or {}).items():
            term, spoken = str(term).strip(), str(spoken).strip()
            if term and spoken:
                unique[term.casefold()] = (term, spoken)
        return cls(tuple(sorted(unique.values(), key=lambda pair: pair[0].casefold())))

    def as_dict(self) -> dict[str, str]:
        return dict(self.entries)

    def overlaid_with(self, other: Lexicon) -> Lexicon:
        """Este léxico com `other` por cima: no mesmo termo, vale o de `other`."""
        return Lexicon.of({**self.as_dict(), **other.as_dict()})

    def __bool__(self) -> bool:
        return bool(self.entries)

    def __len__(self) -> int:
        return len(self.entries)


def _is_word_character(character: str) -> bool:
    return character.isalnum() or character == "_"


def _alternative(index: int, term: str) -> str:
    """Um termo literal; só ganha fronteira de palavra do lado em que começa/termina em letra ou dígito.

    Termos como "C++" ou "Dr." terminam em símbolo: ali a fronteira nunca casaria, e o termo ainda não
    pode casar no meio de uma palavra do lado oposto ("cat" não vale em "category").
    """
    before = r"(?<!\w)" if _is_word_character(term[0]) else ""
    after = r"(?!\w)" if _is_word_character(term[-1]) else ""
    return f"(?P<t{index}>{before}{re.escape(term)}{after})"


@lru_cache(maxsize=64)
def _compiled(lexicon: Lexicon) -> tuple[re.Pattern[str], tuple[str, ...]] | None:
    """Regex única com os termos do maior para o menor, para "Dr. Silva" ganhar de "Dr"."""
    if not lexicon:
        return None
    by_length = sorted(lexicon.entries, key=lambda pair: len(pair[0]), reverse=True)
    pattern = "|".join(_alternative(index, term) for index, (term, _) in enumerate(by_length))
    return re.compile(pattern, re.IGNORECASE), tuple(spoken for _, spoken in by_length)


def apply_lexicon(text: str, lexicon: Lexicon) -> str:
    """Troca cada termo (sem diferenciar maiúsculas, só palavra inteira) pela pronúncia, numa única passada.

    Numa passada só, a pronúncia posta nunca é relida como termo: aplicar de novo não muda o resultado.
    """
    compiled = _compiled(lexicon)
    if compiled is None:
        return text
    pattern, spoken_forms = compiled
    return pattern.sub(lambda match: spoken_forms[int(match.lastgroup[1:])], text)


def apply_inline_overrides(text: str) -> str:
    """`[[termo|pronúncia]]` vira `pronúncia` e `[[pronúncia]]` vira `pronúncia`."""
    return _INLINE_OVERRIDE.sub(lambda match: match.group(1).split("|", 1)[-1], text)


def written_text(text: str) -> str:
    """O texto como foi escrito, para legendas: `[[termo|pronúncia]]` vira `termo` e `[[palavra]]` vira `palavra`."""
    return _INLINE_OVERRIDE.sub(lambda match: match.group(1).split("|", 1)[0], text)


def spoken_text(text: str, lexicon: Lexicon) -> str:
    """O que o modelo deve ler: o dicionário vale fora das marcações e a marcação pontual sempre vence.

    As marcações são resolvidas primeiro e o dicionário só vê o texto que ficou entre elas, então uma
    pronúncia escolhida à mão nunca é reescrita pelo dicionário.
    """
    parts: list[str] = []
    cursor = 0
    for match in _INLINE_OVERRIDE.finditer(text):
        parts.append(apply_lexicon(text[cursor : match.start()], lexicon))
        parts.append(apply_inline_overrides(match.group(0)))
        cursor = match.end()
    parts.append(apply_lexicon(text[cursor:], lexicon))
    return "".join(parts)

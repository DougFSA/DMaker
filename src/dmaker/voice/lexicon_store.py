"""Dicionários de pronúncia em disco: um global (`assets/pronunciation.json`) e um por marca.

Cada termo vale para um idioma, porque a grafia que ensina o português a falar "DMaker" estraga a fala
em inglês. O arquivo é um JSON com uma seção por idioma:

    {"en": {"MedlyCare": "Medly Care"}, "pt": {"DMaker": "Di Mêiker"}}

O formato antigo, `{"termo": "pronúncia"}` solto na raiz, continua valendo e conta como português; ao
gravar, o arquivo é reescrito no formato por idioma. O léxico de uma marca vale por cima do global, e um
termo sem entrada no idioma pedido simplesmente não é trocado (o motor lê o texto como está).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import ASSETS_DIR
from .pronunciation import DEFAULT_LANGUAGE, Lexicon, language_code

LEXICON_FILE = "pronunciation.json"
_BRAND_NAME = re.compile(r"^[A-Za-z0-9][\w-]*$")  # nome de pasta: barra "..", "/" e afins


def _parse(data: object, filename: str) -> dict[str, Lexicon]:
    """Lê o JSON nos dois formatos e junta por idioma normalizado (`pt-BR` e `pt` são o mesmo)."""
    if not isinstance(data, dict):
        raise ValueError(f"{filename} deve ser um objeto JSON com os termos por idioma.")
    by_language: dict[str, dict[str, str]] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            by_language.setdefault(language_code(key), {}).update(value)
        else:
            by_language.setdefault(DEFAULT_LANGUAGE, {})[key] = value
    return {language: Lexicon.of(entries) for language, entries in by_language.items()}


class LexiconStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or ASSETS_DIR

    def _brand_dir(self, brand: str) -> Path:
        if not _BRAND_NAME.match(brand):
            raise ValueError(f"Nome de marca inválido: {brand!r}.")
        return self.root / "brands" / brand

    def _path(self, brand: str | None) -> Path:
        return self.root / LEXICON_FILE if brand is None else self._brand_dir(brand) / LEXICON_FILE

    def by_language(self, brand: str | None = None) -> dict[str, Lexicon]:
        """Todos os idiomas do escopo pedido (global ou da marca), sem os idiomas vazios."""
        path = self._path(brand)
        if not path.is_file():
            return {}
        parsed = _parse(json.loads(path.read_text(encoding="utf-8")), path.name)
        return {language: lexicon for language, lexicon in sorted(parsed.items()) if lexicon}

    def list(self, brand: str | None = None, language: str = DEFAULT_LANGUAGE) -> Lexicon:
        """Só os termos do escopo e do idioma pedidos; arquivo ausente é léxico vazio."""
        return self.by_language(brand).get(language_code(language), Lexicon())

    def for_brand(self, brand: str | None = None, language: str | None = DEFAULT_LANGUAGE) -> Lexicon:
        """O que vale ao narrar nesse idioma para a marca: o global com o da marca por cima.

        `language=None` junta todos os idiomas: serve para saber quais termos existem (o glossário da
        dublagem não traduz nenhum deles), não para decidir como falar.
        """
        scopes = [self.by_language()] + ([self.by_language(brand)] if brand is not None else [])
        if language is not None:
            code = language_code(language)
            return _overlaid([scope.get(code, Lexicon()) for scope in scopes])
        return _overlaid([lexicon for scope in scopes for lexicon in scope.values()])

    def add(
        self, term: str, spoken: str, brand: str | None = None, language: str = DEFAULT_LANGUAGE
    ) -> Lexicon:
        """Grava (ou troca) a pronúncia de `term` no escopo e idioma e devolve o léxico desse idioma."""
        if not term.strip() or not spoken.strip():
            raise ValueError("Informe o termo e como ele deve ser falado.")
        code = self._language(language)
        languages = self.by_language(brand)
        updated = languages.get(code, Lexicon()).overlaid_with(Lexicon.of({term: spoken}))
        self._write({**languages, code: updated}, brand)
        return updated

    def remove(self, term: str, brand: str | None = None, language: str = DEFAULT_LANGUAGE) -> Lexicon:
        """Tira `term` (sem diferenciar maiúsculas) do escopo e idioma; termo que não existe é erro."""
        code = self._language(language)
        languages = self.by_language(brand)
        current = languages.get(code, Lexicon())
        remaining = {
            key: value for key, value in current.entries if key.casefold() != term.strip().casefold()
        }
        if len(remaining) == len(current):
            scope = f"da marca {brand}" if brand else "global"
            raise ValueError(f"O termo {term!r} não está no dicionário {scope} (idioma {code}).")
        updated = Lexicon.of(remaining)
        self._write({**languages, code: updated}, brand)
        return updated

    @staticmethod
    def _language(language: str) -> str:
        code = language_code(language)
        if not code:
            raise ValueError("Informe o idioma da pronúncia (ex.: pt, en).")
        return code

    def _write(self, languages: dict[str, Lexicon], brand: str | None) -> None:
        if brand is not None and not self._brand_dir(brand).is_dir():
            raise ValueError(f"Marca {brand!r} não encontrada em {self.root / 'brands'}.")
        path = self._path(brand)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {code: lexicon.as_dict() for code, lexicon in sorted(languages.items()) if lexicon}
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _overlaid(lexicons: list[Lexicon]) -> Lexicon:
    merged = Lexicon()
    for lexicon in lexicons:
        merged = merged.overlaid_with(lexicon)
    return merged

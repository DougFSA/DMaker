"""Design de voz: descreve a voz por atributos e monta o `instruct` que o OmniVoice entende.

Puro. O modelo só aceita estes termos em inglês (qualquer outro dá erro só depois de carregar o
modelo, que leva minutos), por isso a validação acontece aqui, com mensagem em português e
apelidos em português para os termos.
"""

from __future__ import annotations

import re
from typing import ClassVar

from pydantic import field_validator

from ..domain.spec import Strict

GENDERS = {
    "male": ("masculino", "homem"),
    "female": ("feminino", "mulher"),
}
AGES = {
    "child": ("crianca", "infantil"),
    "teenager": ("adolescente", "jovem-adolescente"),
    "young adult": ("jovem", "adulto-jovem", "young-adult"),
    "middle-aged": ("adulto", "meia-idade", "middle aged"),
    "elderly": ("idoso", "idosa", "velho"),
}
PITCHES = {
    "very low pitch": ("muito grave", "muito-grave", "very low"),
    "low pitch": ("grave", "low"),
    "moderate pitch": ("medio", "moderado", "moderate"),
    "high pitch": ("agudo", "high"),
    "very high pitch": ("muito agudo", "muito-agudo", "very high"),
}
ACCENTS = {
    "american accent": ("americano", "american"),
    "british accent": ("britanico", "british"),
    "australian accent": ("australiano", "australian"),
    "chinese accent": ("chines", "chinese"),
    "canadian accent": ("canadense", "canadian"),
    "indian accent": ("indiano", "indian"),
    "korean accent": ("coreano", "korean"),
    "portuguese accent": ("portugues", "portugal", "portuguese"),
    "russian accent": ("russo", "russian"),
    "japanese accent": ("japones", "japanese"),
}
WHISPER = "whisper"


def _fold(text: str) -> str:
    """Minúsculas e sem acento, para casar o que a pessoa digitou com os apelidos."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", plain.strip().lower())


def _resolve(value: str, table: dict[str, tuple[str, ...]], what: str) -> str:
    folded = _fold(value)
    for canonical, aliases in table.items():
        if folded == canonical or folded in aliases:
            return canonical
    options = ", ".join(f"{canonical} ({aliases[0]})" for canonical, aliases in table.items())
    raise ValueError(f"{what} inválido: {value!r}. Opções: {options}.")


class VoiceDesign(Strict):
    """Atributos da voz; todos opcionais, mas é preciso informar pelo menos um."""

    gender: str | None = None
    age: str | None = None
    pitch: str | None = None
    accent: str | None = None
    whisper: bool = False

    _tables: ClassVar[dict[str, tuple[dict[str, tuple[str, ...]], str]]] = {
        "gender": (GENDERS, "Gênero"),
        "age": (AGES, "Faixa etária"),
        "pitch": (PITCHES, "Tom"),
        "accent": (ACCENTS, "Sotaque"),
    }

    @field_validator("gender", "age", "pitch", "accent", mode="before")
    @classmethod
    def _canonical(cls, value: str | None, info) -> str | None:
        if value is None or not str(value).strip():
            return None
        table, label = cls._tables[info.field_name]
        return _resolve(str(value), table, label)

    def to_instruct(self) -> str:
        """Termos separados por vírgula, na ordem em que o modelo os documenta."""
        terms = [
            t
            for t in (self.gender, self.age, self.pitch, WHISPER if self.whisper else None, self.accent)
            if t
        ]
        if not terms:
            raise ValueError(
                "Descreva a voz com pelo menos um atributo: gênero, faixa etária, tom, sotaque ou sussurro."
            )
        return ", ".join(terms)


def parse_instruct(instruct: str) -> VoiceDesign:
    """Valida um `instruct` escrito à mão (aceita os apelidos em português) e devolve o design."""
    values: dict[str, str | bool] = {}
    groups = {"gender": GENDERS, "age": AGES, "pitch": PITCHES, "accent": ACCENTS}
    for raw in re.split(r"\s*[,;]\s*", instruct.strip()):
        if not raw:
            continue
        if _fold(raw) in (WHISPER, "sussurro", "sussurrado"):
            values["whisper"] = True
            continue
        for field, table in groups.items():
            try:
                canonical = _resolve(raw, table, field)
            except ValueError:
                continue
            if field in values and values[field] != canonical:
                raise ValueError(f"Atributos em conflito para {field}: {values[field]!r} e {canonical!r}.")
            values[field] = canonical
            break
        else:
            raise ValueError(
                f"Termo de voz desconhecido: {raw!r}. Use gênero (male/female), idade (child, teenager, "
                "young adult, middle-aged, elderly), tom (very low pitch ... very high pitch), "
                "sotaque (por exemplo british accent) ou whisper."
            )
    return VoiceDesign(**values)

"""Importar Amostras: lê os valores do texto e os entrega como áudio na taxa da mixagem."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ...domain.generators.samples import SampleData
from .registry import FilterSource, GeneratorRequest, register_generator_builder

COMMENT = "#"
# Um arquivo de dados maior que isto (uma hora a 192 kHz) não é um sinal de teste: a leitura recusa em vez de esgotar a memória
MAX_VALUES = 192_000 * 3600


def read_sample_values(path: Path) -> np.ndarray:
    """Os valores do arquivo, um por linha. Linhas vazias e comentários (`#`) são ignorados; uma linha que não é número é
    erro com o número dela. Aceita vírgula decimal, que é como o Brasil escreve."""
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de amostras não encontrado: {path}")
    values: list[float] = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith(COMMENT):
            continue
        try:
            values.append(float(text.replace(",", ".")))
        except ValueError:
            raise ValueError(f"{path.name}, linha {number}: {text!r} não é um número") from None
        if len(values) > MAX_VALUES:
            raise ValueError(f"{path.name}: valores demais (o limite é {MAX_VALUES})")
    if not values:
        raise ValueError(f"{path.name} não tem nenhum valor")
    return np.asarray(values, dtype=np.float64)


def conformed_values(values: np.ndarray, normalize: bool, name: str) -> np.ndarray:
    """Os valores prontos para tocar. Com `normalize`, o maior em módulo vira 1; sem ele, qualquer valor fora de -1..1 é
    recusado dizendo o maior (clipar em silêncio esconderia um arquivo na escala errada)."""
    peak = float(np.max(np.abs(values)))
    if normalize:
        return values if peak == 0.0 else values / peak
    if peak > 1.0:
        raise ValueError(
            f"{name}: há valores fora de -1 a 1 (o maior em módulo é {peak:g}). Ligue `normalize` para ajustá-los"
        )
    return values


def resampled(values: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Leva os valores da taxa do arquivo à da mixagem por interpolação linear (os dados de laboratório são lentos e
    suaves; um filtro de reamostragem pesado só traria toque). Taxas iguais devolvem os mesmos valores."""
    if source_rate == target_rate:
        return values
    frames = max(round(values.size * target_rate / source_rate), 1)
    positions = np.arange(frames) * (source_rate / target_rate)
    return np.interp(positions, np.arange(values.size), values)


@register_generator_builder("sample_data")
def build_sample_data(request: GeneratorRequest) -> FilterSource | np.ndarray:
    data = request.generator
    assert isinstance(data, SampleData)
    if request.resolve is None:
        raise ValueError("o gerador de amostras precisa do projeto para achar o arquivo de texto")
    path = request.resolve(data.src)
    values = conformed_values(read_sample_values(path), data.normalize, path.name)
    return resampled(values, data.sample_rate, request.sample_rate)

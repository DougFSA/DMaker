"""Exportação múltipla de áudio: que arquivos saem, de que trecho e com que nome (o "Export Multiple" do Audacity).

Funções puras sobre os marcadores da spec: não tocam disco nem o ffmpeg. Quem renderiza cada arquivo é
`pipeline/audio_export.py`. Os quatro modos:

- `mix`: o projeto inteiro num arquivo (o que o render já faz; entra aqui para o plano ser um só);
- `regions`: um arquivo por região de marcador (`Marker` com `start` e `end`), com o texto do marcador no nome;
- `stems`: um arquivo por trilha de som (narração, voz gravada, música, efeitos, som dos trechos);
- `selection`: só o intervalo `[início, fim)`, cada ponta como segundos ou `marker:<texto>`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .markers import MarkerError, find_marker, is_marker_ref, resolve_instant
from .spec import Marker

ExportMode = Literal["mix", "regions", "stems", "selection"]
EXPORT_MODES: tuple[ExportMode, ...] = ("mix", "regions", "stems", "selection")

# nome do arquivo de cada trilha: o id da trilha (o mesmo da vista da linha do tempo) e o que ela contém
STEM_NAMES: dict[str, str] = {
    "A1": "A1-trechos",
    "NAR": "NAR-narracao",
    "VO": "VO-voz-gravada",
    "MUS": "MUS-musica",
    "SFX": "SFX-efeitos",
}

# o Windows não deixa criar arquivo com estes nomes, com ou sem extensão
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
)
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_NAME_LENGTH = 80  # sobra folga para o caminho da pasta, que no Windows passa fácil de 200 caracteres


@dataclass(frozen=True)
class ExportRequest:
    """O que a pessoa pediu para exportar. Os campos de um modo não valem nos outros."""

    mode: ExportMode = "mix"
    group: str | None = None  # regions: só as regiões deste grupo de marcadores (None = todas)
    pauses: bool = False  # regions: também o áudio entre uma região e a próxima, em arquivos `pausa-NN`
    numbered: bool = False  # regions: número na frente do nome (`01 - Introdução`)
    start: float | str | None = None  # selection: segundos ou marker:<texto>
    end: float | str | None = None  # selection: segundos ou marker:<texto>; None = até o fim
    tracks: tuple[str, ...] = ()  # stems: quais trilhas (vazio = as que o projeto tem)


@dataclass(frozen=True)
class ExportFile:
    """Um arquivo a gerar: o nome (sem extensão), o trecho do projeto e, nas trilhas, qual."""

    name: str
    start: float
    end: float | None  # None = até o fim do projeto
    track: str | None = None
    kind: Literal["mix", "region", "pause", "selection", "stem"] = "mix"

    @property
    def duration(self) -> float | None:
        return None if self.end is None else self.end - self.start


def sanitize_file_name(text: str) -> str:
    """O texto de um marcador como nome de arquivo do Windows: sem caracteres proibidos, sem ponto nem espaço no fim,
    sem nome reservado e com tamanho limitado. Vazio se não sobra nada."""
    cleaned = _INVALID_CHARS.sub(" ", unicodedata.normalize("NFC", text))
    cleaned = " ".join(cleaned.split()).strip(" .")[:MAX_NAME_LENGTH].strip(" .")
    if cleaned.casefold() in _RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned


def regions_of(markers: Sequence[Marker], group: str | None = None) -> list[Marker]:
    """As regiões (marcadores com início e fim), em ordem de início, do grupo pedido ou de todos."""
    regions = [m for m in markers if m.is_region and (group is None or m.group == group)]
    return sorted(regions, key=lambda m: (m.begin, m.finish))


def region_files(
    markers: Sequence[Marker], group: str | None = None, *, pauses: bool = False, numbered: bool = False
) -> list[ExportFile]:
    """Um arquivo por região, em ordem. O nome é o texto do marcador saneado; região sem texto, ou com um texto que
    outra repete, ganha o número dela (`regiao-03`, `Introdução-02`), para dois arquivos nunca caírem no mesmo nome.
    Com `numbered` todo nome leva o número na frente, como o "numeração antes do nome" do Audacity.

    Com `pauses`, o áudio que fica fora das regiões entre o começo do projeto e a última delas sai em arquivos
    `pausa-NN`: antes da primeira região e entre uma e a próxima."""
    regions = regions_of(markers, group)
    if not regions:
        where = f" no grupo {group!r}" if group else ""
        raise MarkerError(
            f"o projeto não tem regiões{where}: marque trechos com início e fim (marcadores do tipo região) "
            "para exportar um arquivo por região"
        )
    digits = max(2, len(str(len(regions))))
    bases = [sanitize_file_name(region.text) for region in regions]
    seen: dict[str, int] = {}
    for base in bases:
        seen[base.casefold()] = seen.get(base.casefold(), 0) + 1
    files: list[ExportFile] = []
    for position, (region, base) in enumerate(zip(regions, bases, strict=True), 1):
        number = f"{position:0{digits}d}"
        if not base:
            name = f"regiao-{number}"
        elif seen[base.casefold()] > 1:
            name = f"{base}-{number}"
        else:
            name = base
        if numbered:
            name = f"{number} - {name}"
        files.append(ExportFile(name, region.begin, region.finish, kind="region"))
    if pauses:
        files = sorted([*files, *_pause_files(regions, digits)], key=lambda item: (item.start, item.kind))
    return files


def _pause_files(regions: Sequence[Marker], digits: int) -> list[ExportFile]:
    """Os vazios entre as regiões (que podem se sobrepor): de 0 até a primeira e de cada fim até o próximo início."""
    gaps: list[tuple[float, float]] = []
    reached = 0.0
    for region in regions:
        if region.begin - reached > 1e-3:
            gaps.append((reached, region.begin))
        reached = max(reached, region.finish)
    return [
        ExportFile(f"pausa-{position:0{digits}d}", start, end, kind="pause")
        for position, (start, end) in enumerate(gaps, 1)
    ]


def selection_file(
    markers: Sequence[Marker], start: float | str | None, end: float | str | None
) -> ExportFile:
    """O intervalo `[início, fim)` pedido. Cada ponta é um número de segundos ou `marker:<texto>`; no `marker:` de uma
    região, o início vale o começo dela e o fim vale o fim dela, então `start="marker:Introdução"` e
    `end="marker:Introdução"` exportam exatamente aquela região."""
    first = 0.0 if start is None else _instant(markers, start, "start", at_end=False)
    last = None if end is None else _instant(markers, end, "end", at_end=True)
    if first < 0:
        raise MarkerError(f"start da seleção não pode ser negativo (veio {first:g} s)")
    if last is not None and last <= first:
        raise MarkerError(f"o fim da seleção ({last:g} s) precisa ser depois do início ({first:g} s)")
    return ExportFile("selecao", first, last, kind="selection")


def _instant(markers: Sequence[Marker], value: float | str, what: str, *, at_end: bool) -> float:
    """Segundos, ou o instante de um `marker:`. Num `marker:` de região, o fim da seleção é o fim da região."""
    if is_marker_ref(value):
        marker = markers[find_marker(markers, str(value))]
        return marker.finish if at_end else marker.begin
    return resolve_instant(value, markers, what)


def stem_files(available: Sequence[str], wanted: Sequence[str] = ()) -> list[ExportFile]:
    """Um arquivo por trilha. `wanted` vazio = todas as que o projeto tem; uma trilha pedida que o projeto não tem é
    erro, dizendo quais existem."""
    unknown = [track for track in wanted if track not in STEM_NAMES]
    if unknown:
        raise MarkerError(
            f"trilha desconhecida: {', '.join(unknown)} (as trilhas de som são {', '.join(STEM_NAMES)})"
        )
    missing = [track for track in wanted if track not in available]
    if missing:
        have = ", ".join(available) or "nenhuma"
        raise MarkerError(f"o projeto não tem a trilha {', '.join(missing)} (as que ele tem: {have})")
    tracks = [track for track in STEM_NAMES if track in (wanted or available)]
    if not tracks:
        raise MarkerError(
            "o projeto não tem nenhuma trilha de som para exportar (sem narração, voz, música...)"
        )
    return [ExportFile(STEM_NAMES[track], 0.0, None, track=track, kind="stem") for track in tracks]


def available_stems(
    *, has_clips: bool, narrations: int, voice_files: int, has_music: bool, has_sfx: bool
) -> list[str]:
    """As trilhas de som que o projeto tem: só entram as que têm o que tocar."""
    present = {
        "A1": has_clips,
        "NAR": narrations > 0,
        "VO": voice_files > 0,
        "MUS": has_music,
        "SFX": has_sfx,
    }
    return [track for track in STEM_NAMES if present[track]]

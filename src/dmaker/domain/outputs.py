"""O tipo da saída de um projeto: vídeo (preset de plataforma) ou só áudio (preset de formato de arquivo).

Os dois tipos de preset vivem em registros separados (`domain/presets.py` e `domain/audio_presets.py`); aqui fica
o que decide entre eles pelo nome, para quem renderiza, valida ou lista não precisar de um `if` por tipo. O
renderizador de cada tipo é registrado em `pipeline/output_kinds.py`.
"""

from __future__ import annotations

from typing import Literal

from .audio_presets import AudioPreset, get_audio_preset, is_audio_preset, list_audio_presets
from .presets import Preset, get_preset, list_presets

OutputKind = Literal["video", "audio"]
OutputPreset = Preset | AudioPreset

# O contexto de render pede um quadro mesmo quando não há imagem (o tamanho entra em contas que o áudio não usa):
# o projeto só de áudio usa este preset como quadro neutro, sem nunca desenhar nada nele.
FRAME_STAND_IN = "youtube/video"


def output_kind(preset_name: str | None) -> OutputKind:
    """`audio` para o nome de um preset de áudio (`audio/mp3` ou o apelido `mp3`), `video` para o resto."""
    return "audio" if is_audio_preset(preset_name) else "video"


def resolve_output(name: str) -> OutputPreset:
    """O preset de vídeo ou de áudio com esse nome (ou apelido); `KeyError` com as opções se não existe."""
    if is_audio_preset(name):
        return get_audio_preset(name)
    return get_preset(name)


def frame_preset(name: str) -> Preset:
    """O preset de vídeo do nome, ou o quadro neutro quando a saída é de áudio."""
    return get_preset(FRAME_STAND_IN if output_kind(name) == "audio" else name)


def list_outputs() -> list[OutputPreset]:
    """Todos os presets, os de vídeo primeiro."""
    return [*list_presets(), *list_audio_presets()]


def output_extension(preset: OutputPreset) -> str:
    """A extensão do arquivo que o preset gera: `.mp4` no vídeo, a do formato no áudio (`.mp3`, `.wav`...)."""
    return preset.extension if isinstance(preset, AudioPreset) else ".mp4"

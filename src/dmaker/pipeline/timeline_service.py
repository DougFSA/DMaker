"""A vista de linha do tempo de um projeto, calculada do disco: o serviço que a interface e o MCP chamam.

Separado de `timeline_view.py` (que só monta a vista a partir de um layout já calculado, sem tocar disco)
porque aqui se olha para os arquivos: o editor precisa abrir o projeto mesmo quando uma fonte foi movida ou
apagada, e então o trecho dela aparece marcado como "fonte não encontrada" em vez de a vista falhar.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.audio_effects import active_effects
from ..domain.music_tempo import music_chain
from ..domain.spec import Project
from ..media.probe import probe
from .context import Prober
from .layout import project_layout
from .missing import MissingMedia
from .persona_speech_store import persona_view
from .sync import OffsetFinder
from .timeline_view import TimelineView, build_timeline_view
from .voicefiles import music_file_playtime, voice_file_playtimes


def project_timeline_view(
    project: Project,
    narration_durations: Sequence[float | None] = (),
    prober: Prober = probe,
    offset_finder: OffsetFinder | None = None,
) -> TimelineView:
    """Vista multitrilha do projeto, com os itens de arquivo ausente marcados (`TrackItem.missing`)."""
    missing = MissingMedia.scan(project)
    layout = project_layout(project, prober, offset_finder, missing)
    return build_timeline_view(
        project,
        layout,
        music_duration=_music_duration_after_effects(project, prober),
        narration_durations=narration_durations,
        missing=missing,
        voiceover_durations=voice_file_playtimes(project, prober),  # já depois dos efeitos (o Repetir cresce)
        personas=persona_view(project),
    )


def _music_duration_after_effects(project: Project, prober: Prober) -> float | None:
    """A duração do arquivo da música quando os efeitos dela a mudam (o Mudar Andamento, o Paulstretch), senão None: a
    vista só a usa então, e uma música sem efeito de tempo segue sem o custo de sondar o arquivo."""
    music = project.audio.music
    if music is None or not any(
        effect.alters_duration() for _, effect in active_effects(music_chain(project.audio))
    ):
        return None
    return music_file_playtime(project, prober)

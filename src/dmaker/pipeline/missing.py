"""Arquivos que sumiram do disco, tolerados só onde o editor precisa abrir o projeto mesmo assim.

O render e a validação continuam exigindo todos os arquivos (um vídeo sem a fonte não sai). Já a vista de
linha do tempo e as edições precisam abrir um projeto cujo arquivo foi movido: o trecho aparece marcado como
"fonte não encontrada" e a pessoa troca o arquivo. `MissingMedia` é a política que a resolução das fontes
recebe para isso: com ela, o arquivo ausente vira um substituto sem imagem nem som, em vez de uma exceção.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain.spec import ClipSegment, ImageOverlay, ImageSegment, Project, VideoOverlay
from ..media.probe import MediaInfo

# duração do substituto de um clipe sem `end`: o arquivo que diria o tamanho dele não existe mais
STAND_IN_DURATION_S = 10.0


@dataclass
class MissingMedia:
    """Os arquivos que a spec cita e o disco não tem, e quanto cada um deve durar no lugar do original."""

    paths: set[Path] = field(default_factory=set)
    durations: dict[Path, float] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.paths)

    def covers(self, *paths: Path | str | None) -> bool:
        """Algum destes caminhos é um arquivo ausente."""
        return any(path is not None and Path(path) in self.paths for path in paths)

    def stand_in(self, path: Path) -> MediaInfo:
        """Mídia no lugar do arquivo ausente: com vídeo e sem áudio, e com a duração que a spec já pede (o maior
        `end` dos clipes que o usam), para os trechos manterem o tamanho que tinham na linha do tempo."""
        duration = self.durations.get(path, STAND_IN_DURATION_S)
        return MediaInfo(path, duration, 0, 0, 0.0, True, False, False)

    @classmethod
    def scan(cls, project: Project) -> MissingMedia:
        """Confere no disco cada arquivo de mídia que a spec cita (ver `media_references`)."""
        found = cls()
        needed: dict[Path, float] = {}
        for raw, end in media_references(project):
            path = project.resolve(raw)
            if path.exists():
                continue
            found.paths.add(path)
            needed[path] = max(needed.get(path, 0.0), end or 0.0)
        found.durations = {path: max(end, STAND_IN_DURATION_S) for path, end in needed.items()}
        return found


def media_references(project: Project) -> list[tuple[str, float | None]]:
    """Cada arquivo de mídia que a spec cita (trechos, fontes, sobreposições, música e locuções), como a spec o
    escreve, com o fim mais distante que um clipe pede dele (None quando nenhum pede). Função pura: quem
    chama olha o disco, seja para achar o que falta, seja para carimbar a chave de um cache."""
    found: list[tuple[str, float | None]] = []
    for segment in project.timeline:
        if isinstance(segment, ClipSegment):
            last = segment.end if segment.end is not None else segment.start + STAND_IN_DURATION_S
            if segment.source:
                ref = project.sources.get(segment.source)
                found.extend((raw, last) for raw in (ref.files if ref else []))
            elif segment.src:
                found.append((segment.src, last))
        elif isinstance(segment, ImageSegment):
            found.append((segment.src, None))
    for ref in project.sources.values():
        found.extend((raw, None) for raw in ref.files)
    for overlay in project.overlays:
        if isinstance(overlay, VideoOverlay) and overlay.src:
            found.append((overlay.src, None))
        elif (
            isinstance(overlay, ImageOverlay)
            and overlay.src != "logo"
            and not overlay.src.startswith("logo:")
        ):
            found.append((overlay.src, None))
    if project.audio.music is not None:
        found.append((project.audio.music.src, None))
    found.extend((clip.src, None) for clip in project.audio.voiceover)
    return found

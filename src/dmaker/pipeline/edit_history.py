"""Desfazer e refazer para toda operação do `edit_project`: a pilha de specs anteriores, guardada na pasta do projeto.

Generaliza o desfazer do corte automático (`undo_cut`, que devolve um corte pelo número dele): aqui cada edição grava
o estado de ANTES e `undo_edit` volta a ele, byte a byte, deixando o estado de depois na pilha do `redo_edit`. Uma
edição nova esvazia a pilha do refazer, como em qualquer editor. A pilha tem limite de passos (os mais antigos saem).

Em disco, em `<projeto>/history/`: um `index.json` com as duas pilhas e, por passo, o `<id>.spec.json` com os bytes
exatos da spec (e, se o passo mexeu neles, os arquivos ao lado que ele restaura, como a lista de cortes). A interface
tem o desfazer próprio, em memória, e não passa por aqui: só quem grava a spec em disco registra (MCP e CLI).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..domain.atomic_file import content_revision, read_bytes_retrying, write_bytes_atomic
from ..domain.spec import Project
from ..media.probe import probe
from .context import Prober
from .edit_outcome import EditReport
from .edits import apply_edit_report
from .projects import load_project, project_path, save_project
from .sample_reader import SampleReader
from .sync import OffsetFinder

if TYPE_CHECKING:
    from .censor import WordSource

HISTORY_DIR = "history"
HISTORY_LIMIT = 50  # passos que ficam em cada pilha: o bastante para uma sessão, sem encher o disco de specs
INDEX_FILE = "index.json"
INDEX_VERSION = 1
LABEL_DETAIL_LIMIT = 90


class HistoryError(ValueError):
    """Não há o que desfazer ou refazer, ou a pilha do projeto está ilegível."""


# como cada operação se chama para quem lê a lista de passos
OPERATION_LABELS = {
    "split": "Cortar no cursor",
    "remove": "Remover trecho",
    "move": "Mover trecho",
    "trim": "Aparar trecho",
    "duplicate": "Duplicar trecho",
    "insert": "Inserir trecho",
    "overlay_span": "Ajustar sobreposição",
    "overlay_remove": "Remover sobreposição",
    "overlay_duplicate": "Duplicar sobreposição",
    "set_field": "Mudar campo",
    "audio_effect": "Efeito de áudio",
    "auto_duck_add": "Auto Duck novo",
    "auto_duck_set": "Ajustar Auto Duck",
    "auto_duck_remove": "Remover Auto Duck",
    "marker_add": "Marcador novo",
    "marker_set": "Editar marcador",
    "marker_remove": "Remover marcador",
    "marker_group_set": "Marcadores da análise de áudio",
    "generated_add": "Som gerado",
    "generated_set": "Ajustar som gerado",
    "generated_remove": "Remover som gerado",
    "censor_beep": "Bipe de censura",
    "audio_silence": "Silenciar",
    "audio_cut": "Cortar som",
    "audio_envelope": "Envelope de volume",
    "audio_channels": "Canais",
    "audio_trim": "Aparar fora da seleção",
    "audio_paste": "Colar som",
    "audio_duplicate": "Duplicar som",
    "audio_split": "Dividir voz",
    "audio_join": "Juntar vozes",
    "audio_shift": "Deslocar som",
    "audio_split_stereo": "Dividir estéreo",
    "track_set": "Estado da trilha",
    "noise_profile_set": "Perfil de ruído",
    "noise_profile_remove": "Apagar perfil de ruído",
    "audio_truncate_silence": "Truncar silêncio",
    "audio_fade": "Fade na borda",
    "audio_crossfade_tracks": "Crossfade de trilhas",
    "audio_crossfade_clips": "Crossfade de som entre clipes",
}
_DETAIL_KEYS = (
    "name",
    "target",
    "track",
    "index",
    "action",
    "start",
    "end",
    "region",
    "at",
    "delta",
    "to",
    "mode",
    "side",
    "kind",
    "out_target",
    "in_target",
)


def edit_label(op: Mapping) -> str:
    """O nome do passo no histórico: a operação e o que ela pegou (`Silenciar target=timeline.0 start=4 end=6`)."""
    name = OPERATION_LABELS.get(str(op.get("type")), str(op.get("type")))
    detail = " ".join(f"{key}={op[key]}" for key in _DETAIL_KEYS if key in op)
    label = f"{name} {detail}".strip()
    return label if len(label) <= LABEL_DETAIL_LIMIT else label[: LABEL_DETAIL_LIMIT - 1] + "…"


@dataclass(frozen=True)
class HistoryStep:
    """Um passo de uma pilha: o arquivo da spec que ele guarda, o nome, quando foi gravado, a revisão que a spec do
    projeto deve ter quando o passo for aplicado (se for outra, houve mudança fora do histórico) e os arquivos ao
    lado que ele restaura."""

    id: str
    label: str
    at: str
    expects: str
    sidecars: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "at": self.at,
            "expects": self.expects,
            "sidecars": list(self.sidecars),
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> HistoryStep:
        return cls(
            str(data["id"]),
            str(data["label"]),
            str(data["at"]),
            str(data["expects"]),
            tuple(data["sidecars"]),
        )


@dataclass
class HistoryState:
    """As duas pilhas (a última posição é o passo mais recente) e o próximo número de passo."""

    undo: list[HistoryStep] = field(default_factory=list)
    redo: list[HistoryStep] = field(default_factory=list)
    next_id: int = 1


@dataclass(frozen=True)
class HistoryOutcome:
    """O que um desfazer ou refazer fez: o projeto de agora, o nome do passo, quantos sobram em cada pilha e os
    avisos (a spec tinha mudado fora do histórico: o estado dela ficou guardado e o `redo_edit` o devolve)."""

    project: Project
    path: Path
    label: str
    undo_steps: int
    redo_steps: int
    warnings: list[str] = field(default_factory=list)


class EditHistory:
    """A pilha de desfazer e refazer de UM projeto, na pasta dele."""

    def __init__(self, folder: Path, limit: int = HISTORY_LIMIT, spec_path: Path | None = None) -> None:
        self.folder = folder
        self.directory = folder / HISTORY_DIR
        self.limit = limit
        self.spec_path = spec_path or folder / "spec.json"

    # ---------- disco ----------

    def _load(self) -> HistoryState:
        index = self.directory / INDEX_FILE
        if not index.exists():
            return HistoryState()
        try:
            data = json.loads(read_bytes_retrying(index).decode("utf-8"))
            return HistoryState(
                [HistoryStep.from_dict(item) for item in data["undo"]],
                [HistoryStep.from_dict(item) for item in data["redo"]],
                int(data["next"]),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HistoryError(
                f"o histórico do projeto está ilegível ({exc}); apague a pasta {HISTORY_DIR}"
            ) from exc

    def _save(self, state: HistoryState) -> None:
        data = {
            "version": INDEX_VERSION,
            "next": state.next_id,
            "undo": [step.to_dict() for step in state.undo],
            "redo": [step.to_dict() for step in state.redo],
        }
        write_bytes_atomic(
            self.directory / INDEX_FILE, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
        )

    def _spec_file(self, step: HistoryStep) -> Path:
        return self.directory / f"{step.id}.spec.json"

    def _sidecar_file(self, step: HistoryStep, name: str) -> Path:
        return self.directory / f"{step.id}.{name}"

    def _drop(self, step: HistoryStep) -> None:
        self._spec_file(step).unlink(missing_ok=True)
        for name in step.sidecars:
            self._sidecar_file(step, name).unlink(missing_ok=True)

    def _keep(
        self, state: HistoryState, label: str, spec: bytes, expects: str, sidecars: Mapping[str, str]
    ) -> HistoryStep:
        """Grava os arquivos de um passo novo e devolve o passo (ainda fora das pilhas)."""
        step = HistoryStep(
            f"{state.next_id:06d}",
            label,
            datetime.now().isoformat(timespec="seconds"),
            expects,
            tuple(sidecars),
        )
        state.next_id += 1
        write_bytes_atomic(self._spec_file(step), spec)
        for name, text in sidecars.items():
            write_bytes_atomic(self._sidecar_file(step, name), text.encode("utf-8"))
        return step

    def _sidecars_now(self, names: tuple[str, ...]) -> dict[str, str]:
        return {
            name: (self.folder / name).read_text(encoding="utf-8")
            for name in names
            if (self.folder / name).exists()
        }

    # ---------- gravar ----------

    def record(
        self, before: Project, after: Project, label: str, sidecars: Mapping[str, str] | None = None
    ) -> None:
        """Guarda `before` como o estado a que o desfazer volta depois da edição `label`, que levou o projeto a
        `after`. Uma edição nova esvazia a pilha do refazer e, passando do limite, as mais antigas saem."""
        state = self._load()
        step = self._keep(state, label, before.to_bytes(), content_revision(after.to_bytes()), sidecars or {})
        for stale in state.redo:
            self._drop(stale)
        state.redo = []
        state.undo.append(step)
        while len(state.undo) > self.limit:
            self._drop(state.undo.pop(0))
        self._save(state)

    # ---------- desfazer e refazer ----------

    def steps(self) -> HistoryState:
        return self._load()

    def undo(self, current: Project) -> tuple[Project, HistoryStep, list[str]]:
        return self._move(current, undoing=True)

    def redo(self, current: Project) -> tuple[Project, HistoryStep, list[str]]:
        return self._move(current, undoing=False)

    def _move(self, current: Project, undoing: bool) -> tuple[Project, HistoryStep, list[str]]:
        """Aplica o passo do topo de uma pilha: restaura a spec dele e põe a de agora no topo da outra pilha."""
        state = self._load()
        source, target = (state.undo, state.redo) if undoing else (state.redo, state.undo)
        if not source:
            raise HistoryError(
                "não há o que desfazer neste projeto" if undoing else "não há o que refazer neste projeto"
            )
        step = source.pop()
        spec = read_bytes_retrying(self._spec_file(step))
        warnings: list[str] = []
        now = content_revision(current.to_bytes())
        if step.expects and now != step.expects:
            warnings.append(
                "O projeto tinha mudado fora do histórico desde a última edição (na interface ou à mão): "
                + ("o desfazer" if undoing else "o refazer")
                + " o trocou pelo estado guardado. O estado de agora ficou na pilha do "
                + ("refazer (`redo_edit` o devolve)." if undoing else "desfazer (`undo_edit` o devolve).")
            )
        restored = Project.from_bytes(spec, self.folder.resolve())
        target.append(
            self._keep(
                state,
                step.label,
                current.to_bytes(),
                content_revision(spec),
                self._sidecars_now(step.sidecars),
            )
        )
        write_bytes_atomic(self.spec_path, spec)
        for name in step.sidecars:
            (self.folder / name).write_text(
                self._sidecar_file(step, name).read_text(encoding="utf-8"), encoding="utf-8"
            )
        self._drop(step)
        self._save(state)
        return restored, step, warnings


# ---------- os serviços que a CLI e o MCP chamam ----------


def _history_for(project: Project, name_or_path: str | Path) -> EditHistory:
    spec_path = project_path(name_or_path)
    return EditHistory(project.base_dir or spec_path.parent, spec_path=spec_path)


def edit_and_record(
    name_or_path: str | Path,
    op: dict,
    prober: Prober = probe,
    offset_finder: OffsetFinder | None = None,
    sample_reader: SampleReader | None = None,
    words: WordSource | None = None,
) -> tuple[EditReport, Path]:
    """Aplica a operação à spec do projeto, guarda o estado de antes no histórico e grava a spec nova. Só a edição que
    deu certo entra no histórico, e ele é gravado antes da spec, para uma falha no meio nunca deixar a spec nova sem o
    passo que a desfaz."""
    project = load_project(name_or_path)
    report = apply_edit_report(project, op, prober, offset_finder, sample_reader, words)
    _history_for(project, name_or_path).record(project, report.project, edit_label(op))
    path = save_project(report.project, project.base_dir)
    return report, path


def undo_edit(name_or_path: str | Path) -> HistoryOutcome:
    """Desfaz a última edição gravada: a spec volta exatamente a como estava antes dela."""
    return _step(name_or_path, undoing=True)


def redo_edit(name_or_path: str | Path) -> HistoryOutcome:
    """Refaz a última edição desfeita (a pilha do refazer se esvazia com qualquer edição nova)."""
    return _step(name_or_path, undoing=False)


def _step(name_or_path: str | Path, undoing: bool) -> HistoryOutcome:
    current = load_project(name_or_path)
    history = _history_for(current, name_or_path)
    restored, step, warnings = history._move(current, undoing)
    state = history.steps()
    return HistoryOutcome(
        restored, project_path(name_or_path), step.label, len(state.undo), len(state.redo), warnings
    )


def history_listing(name_or_path: str | Path) -> dict:
    """Os passos do histórico, do mais recente para o mais antigo: o que `undo_edit` desfaria e o que `redo_edit` refaria."""
    project = load_project(name_or_path)
    state = _history_for(project, name_or_path).steps()
    return {
        "undo": [{"label": step.label, "at": step.at} for step in reversed(state.undo)],
        "redo": [{"label": step.label, "at": step.at} for step in reversed(state.redo)],
        "limit": HISTORY_LIMIT,
    }

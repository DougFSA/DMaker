"""Gravar do microfone na spec: a gravação vira voz gravada, o punch-in troca só o trecho e guarda o take antigo.

Sem ffmpeg (a sonda é falsa): o que se confere é o que as operações escrevem na spec. O som de verdade, sem estalo nas
emendas, está em `test_recording_integration.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.edits import EditError
from dmaker.domain.spec import Project
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.edits import apply_edit

DURATIONS = {"video.mp4": 20.0, "fala.wav": 6.0, "take.wav": 5.0, "take2.wav": 5.0}


def prober(path: Path) -> MediaInfo:
    video = path.suffix == ".mp4"
    return MediaInfo(
        path,
        DURATIONS.get(path.name, 5.0),
        1280 if video else 0,
        720 if video else 0,
        30.0,
        video,
        True,
        False,
    )


@pytest.fixture
def folder(tmp_path) -> Path:
    (tmp_path / "rec").mkdir()
    for name in DURATIONS:
        folder = tmp_path / "rec" if name.startswith("take") else tmp_path
        (folder / name).write_bytes(b"\x00" * 16)
    return tmp_path


def make(folder: Path, voiceover: list[dict] | None = None) -> Project:
    project = Project.model_validate(
        {
            "name": "gravacao",
            "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 20}],
            "audio": {"voiceover": voiceover if voiceover is not None else [{"src": "fala.wav", "start": 2}]},
        }
    )
    project.base_dir = folder
    return project


def edit(project: Project, **op) -> Project:
    return apply_edit(project, op, prober=prober)


def test_a_gravacao_vira_voz_gravada_no_instante_pedido(folder):
    project = edit(make(folder, []), type="audio_record_add", src="rec/a.wav", start=3.5, duration=4.0)
    clip = project.audio.voiceover[0]
    assert (clip.src, clip.start, clip.offset, clip.end) == ("rec/a.wav", 3.5, 0.0, None)


def test_latencia_que_leva_o_inicio_para_antes_de_zero_apara_o_comeco_do_arquivo(folder):
    project = edit(make(folder, []), type="audio_record_add", src="rec/a.wav", start=-0.12, duration=4.0)
    clip = project.audio.voiceover[0]
    assert (clip.start, clip.offset) == (0.0, 0.12)


def test_gravacao_vazia_e_recusada(folder):
    with pytest.raises(EditError, match="vazia"):
        edit(make(folder, []), type="audio_record_add", src="rec/a.wav", start=0, duration=0)


def test_punch_in_divide_em_tres_e_o_meio_usa_o_take_novo(folder):
    # a voz toca de 2 a 8 s do vídeo; o take começou em 3 s do vídeo e dura 5 s; punch de 4 a 7 s
    project = edit(
        make(folder),
        type="audio_punch",
        target="audio.voiceover.0",
        start=4,
        end=7,
        src="rec/take.wav",
        recorded_at=3.0,
        duration=5.0,
    )
    before, middle, after = project.audio.voiceover
    assert (before.src, before.start, before.offset, before.end) == ("fala.wav", 2, 0, 2)
    assert (middle.src, middle.start, middle.offset, middle.end) == ("rec/take.wav", 4, 1.0, 4.0)
    assert (after.src, after.start, after.offset, after.end) == ("fala.wav", 7, 5, None)
    assert after.takes == [] and before.takes == []


def test_o_take_antigo_fica_disponivel_na_lista_do_trecho(folder):
    project = edit(
        make(folder),
        type="audio_punch",
        target="audio.voiceover.0",
        start=4,
        end=7,
        src="rec/take.wav",
        recorded_at=3.0,
        duration=5.0,
    )
    middle = project.audio.voiceover[1]
    assert [(t.src, t.offset, t.end, t.label) for t in middle.takes] == [("fala.wav", 2.0, 5.0, "Original")]
    assert middle.take_label == "Take 2"


def test_emendas_levam_fade_de_10_ms_dos_dois_lados(folder):
    project = edit(
        make(folder),
        type="audio_punch",
        target="audio.voiceover.0",
        start=4,
        end=7,
        src="rec/take.wav",
        recorded_at=3.0,
        duration=5.0,
    )
    before, middle, after = project.audio.voiceover

    def fades(clip):
        return sorted((e.type, e.duration) for e in clip.effects if e.type.startswith("fade_"))

    assert fades(before) == [("fade_out", 0.01)]
    assert fades(middle) == [("fade_in", 0.01), ("fade_out", 0.01)]
    assert fades(after) == [("fade_in", 0.01)]


def test_a_duracao_total_da_voz_nao_muda(folder):
    project = edit(
        make(folder),
        type="audio_punch",
        target="audio.voiceover.0",
        start=4,
        end=7,
        src="rec/take.wav",
        recorded_at=3.0,
        duration=5.0,
    )
    covered = sum(
        ((c.end - c.offset) if c.end is not None else 6.0 - c.offset) for c in project.audio.voiceover
    )
    assert covered == pytest.approx(6.0)


def test_punch_no_comeco_nao_cria_o_item_de_antes(folder):
    project = edit(
        make(folder),
        type="audio_punch",
        target="audio.voiceover.0",
        start=2,
        end=5,
        src="rec/take.wav",
        recorded_at=2.0,
        duration=5.0,
    )
    assert len(project.audio.voiceover) == 2
    assert project.audio.voiceover[0].src == "rec/take.wav"


def test_gravacao_que_parou_antes_do_fim_troca_so_o_que_gravou(folder):
    # pediu de 4 a 7 s, mas a gravação (começou em 3 s) tem só 2 s: troca de 4 a 5 s
    project = edit(
        make(folder),
        type="audio_punch",
        target="audio.voiceover.0",
        start=4,
        end=7,
        src="rec/take.wav",
        recorded_at=3.0,
        duration=2.0,
    )
    middle = project.audio.voiceover[1]
    assert (middle.start, middle.offset, middle.end) == (4, 1.0, 2.0)
    assert project.audio.voiceover[2].start == 5


def test_punch_sem_gravacao_no_trecho_e_recusado(folder):
    with pytest.raises(EditError, match="não há som gravado"):
        edit(
            make(folder),
            type="audio_punch",
            target="audio.voiceover.0",
            start=4,
            end=7,
            src="rec/take.wav",
            recorded_at=9.0,
            duration=1.0,
        )


def test_trocar_o_take_leva_o_que_tocava_para_a_lista(folder):
    punched = edit(
        make(folder),
        type="audio_punch",
        target="audio.voiceover.0",
        start=4,
        end=7,
        src="rec/take.wav",
        recorded_at=3.0,
        duration=5.0,
    )
    swapped = edit(punched, type="voiceover_take_set", target="audio.voiceover.1", take=0)
    middle = swapped.audio.voiceover[1]
    assert (middle.src, middle.offset, middle.end, middle.take_label) == ("fala.wav", 2.0, 5.0, "Original")
    assert [(t.src, t.offset, t.end, t.label) for t in middle.takes] == [("rec/take.wav", 1.0, 4.0, "Take 2")]
    again = edit(swapped, type="voiceover_take_set", target="audio.voiceover.1", take=0)
    assert again.audio.voiceover[1].src == "rec/take.wav"


def test_um_segundo_punch_no_mesmo_trecho_acumula_takes(folder):
    first = edit(
        make(folder),
        type="audio_punch",
        target="audio.voiceover.0",
        start=4,
        end=7,
        src="rec/take.wav",
        recorded_at=3.0,
        duration=5.0,
    )
    second = edit(
        first,
        type="audio_punch",
        target="audio.voiceover.1",
        start=4,
        end=7,
        src="rec/take2.wav",
        recorded_at=3.5,
        duration=5.0,
    )
    middle = second.audio.voiceover[1]
    assert len(second.audio.voiceover) == 3  # o trecho inteiro foi trocado: não cria itens vazios
    assert [t.label for t in middle.takes] == ["Take 2", "Original"]
    assert middle.take_label == "Take 3"


def test_trocar_take_de_voz_sem_takes_e_recusado(folder):
    with pytest.raises(EditError, match="não tem takes"):
        edit(make(folder), type="voiceover_take_set", target="audio.voiceover.0", take=0)


def test_take_inexistente_e_recusado(folder):
    punched = edit(
        make(folder),
        type="audio_punch",
        target="audio.voiceover.0",
        start=4,
        end=7,
        src="rec/take.wav",
        recorded_at=3.0,
        duration=5.0,
    )
    with pytest.raises(EditError, match="não existe"):
        edit(punched, type="voiceover_take_set", target="audio.voiceover.1", take=3)


def test_projeto_sem_takes_nao_muda_o_dump_nem_o_hash(folder):
    project = make(folder)
    dumped = project.model_dump(exclude_none=True)["audio"]["voiceover"][0]
    assert "takes" not in dumped and "take_label" not in dumped

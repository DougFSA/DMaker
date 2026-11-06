"""A escolha "ouvir a trilha mesmo muda" do Vocoder (ajuste do DMK-70), sem ffmpeg: as trilhas mantidas, a visão ouvida, os ids das
duas visões, o aviso, o dump que não muda sem o campo e o que o pipeline instala (a mistura intacta e a passada prévia na visão ouvida)."""

from __future__ import annotations

import re

from dmaker.domain.audio_effects import chain_signature, parse_effect
from dmaker.domain.spec import Project
from dmaker.domain.tracks import (
    apply_track_state,
    carrier_heard_project,
    kept_carriers,
    silenced_carrier_warnings,
)


def vocoder(track: str | None = None, ignores: bool = False, **extra) -> dict:
    return {
        "type": "vocoder",
        **({"carrier_track": track} if track else {}),
        **({"carrier_ignores_mute": True} if ignores else {}),
        **extra,
    }


def project_of(
    voice_effects: list[dict], *, tracks: dict | None = None, music: bool = True, **audio
) -> Project:
    """Uma voz gravada com os efeitos dados, três faixas externas (A2, A3, A4), música e narração, com o estado de trilha dado."""
    return Project.model_validate(
        {
            "name": "p",
            "sources": {
                "c": {"src": "v.mp4"},
                "x": {"src": "x.wav"},
                "y": {"src": "y.wav"},
                "z": {"src": "z.wav"},
            },
            "timeline": [{"type": "clip", "source": "c", "start": 0, "end": 5}],
            "audio": {
                "tracks": [{"source": "x"}, {"source": "y"}, {"source": "z"}],
                "voiceover": [{"src": "fala.wav", "effects": voice_effects}],
                "narration": [{"text": "oi"}],
                **({"music": {"src": "m.mp3"}} if music else {}),
                **audio,
            },
            "tracks": tracks or {},
        }
    )


def muted(*ids: str) -> dict:
    return {track_id: {"muted": True} for track_id in ids}


def voice_carrier(project: Project) -> str | None:
    return project.audio.voiceover[0].effects[0].carrier_track_id()


# ---------- as trilhas mantidas ----------


def test_a_muted_track_is_kept_only_when_an_enabled_effect_asks_for_it():
    asked = project_of([vocoder("A3", ignores=True)], tracks=muted("A3"))
    assert kept_carriers(asked) == {"A3"}
    assert kept_carriers(project_of([vocoder("A3")], tracks=muted("A3"))) == set()  # sem a escolha
    off = project_of([{**vocoder("A3", ignores=True), "enabled": False}], tracks=muted("A3"))
    assert kept_carriers(off) == set()  # efeito desligado
    assert kept_carriers(project_of([vocoder("A3", ignores=True)])) == set()  # a trilha soa: nada a manter


def test_a_track_outside_the_solo_is_kept_the_same_way():
    project = project_of([vocoder("MUS", ignores=True)], tracks={"VO": {"solo": True}})
    assert kept_carriers(project) == {"MUS"}
    assert carrier_heard_project(project) is not None


def test_a_host_that_does_not_sound_keeps_nothing_unless_another_item_keeps_it():
    # a voz está muda e ouviria a A3 muda: a voz não vai à mistura, então não há o que manter
    project = project_of([vocoder("A3", ignores=True)], tracks=muted("A3", "VO"))
    assert kept_carriers(project) == set() and carrier_heard_project(project) is None


def test_the_fixed_point_keeps_a_muted_chain_where_a_sounding_item_starts_it():
    # a voz soa e ouve a música muda; a música (muda) tem um Vocoder que ouve a narração muda
    project = project_of(
        [vocoder("MUS", ignores=True)],
        tracks=muted("MUS", "NAR"),
        music=True,
    )
    music = project.audio.music.model_copy(update={"effects": [parse_effect(vocoder("NAR", ignores=True))]})
    project = project.model_copy(update={"audio": project.audio.model_copy(update={"music": music})})
    assert kept_carriers(project) == {"MUS", "NAR"}
    # sem o primeiro elo, a música muda não é hospedeira que soa: nada se mantém
    broken = project_of([vocoder(None)], tracks=muted("MUS", "NAR"))
    music = broken.audio.music.model_copy(update={"effects": [parse_effect(vocoder("NAR", ignores=True))]})
    broken = broken.model_copy(update={"audio": broken.audio.model_copy(update={"music": music})})
    assert kept_carriers(broken) == set()


# ---------- a visão ouvida ----------


def test_without_the_choice_there_is_no_heard_view_and_the_mix_is_the_usual_one():
    project = project_of([vocoder("A3")], tracks=muted("A3"))
    assert carrier_heard_project(project) is None
    assert voice_carrier(apply_track_state(project)) is None  # a trilha muda vira a portadora gerada


def test_the_mix_keeps_the_muted_track_out_and_the_heard_view_has_it_back():
    project = project_of([vocoder("A3", ignores=True)], tracks=muted("A3"))
    mix, heard = apply_track_state(project), carrier_heard_project(project)
    assert len(mix.audio.tracks) == 2 and len(heard.audio.tracks) == 3
    assert voice_carrier(mix) == "A3" and voice_carrier(heard) == "A3"  # o id aponta para a ouvida


def test_the_ids_follow_the_heard_view_with_another_muted_track_before_it():
    # A2 muda e não pedida, A3 muda e pedida, A4 soando: a ouvida só perde a A2, então a A3 segue A3 e a A4 vira A3 na mistura
    project = project_of(
        [vocoder("A3", ignores=True), vocoder("A4")],
        tracks=muted("A2", "A3"),
    )
    mix, heard = apply_track_state(project), carrier_heard_project(project)
    assert [t.source for t in mix.audio.tracks] == ["z"]
    assert [t.source for t in heard.audio.tracks] == [
        "y",
        "z",
    ]  # a ouvida tem a A3 (y) e a A4 (z), renumeradas A2 e A3
    mix_ids = [e.carrier_track_id() for e in mix.audio.voiceover[0].effects]
    heard_ids = [e.carrier_track_id() for e in heard.audio.voiceover[0].effects]
    assert mix_ids == heard_ids == ["A2", "A3"]  # A3 -> A2 e A4 -> A3 pela numeração do que sobra na ouvida


def test_two_effects_hearing_the_same_muted_track_one_with_the_choice_and_one_without():
    project = project_of([vocoder("A3", ignores=True), vocoder("A3")], tracks=muted("A3"))
    mix = apply_track_state(project)
    ids = [effect.carrier_track_id() for effect in mix.audio.voiceover[0].effects]
    assert ids == ["A3", None]  # o primeiro mantém o id, e o segundo cai na portadora gerada
    heard = carrier_heard_project(project)
    assert [effect.carrier_track_id() for effect in heard.audio.voiceover[0].effects] == ["A3", "A3"]


def test_the_ducks_follow_the_mix_and_not_the_heard_view():
    project = project_of(
        [vocoder("A3", ignores=True)],
        tracks=muted("A3"),
        ducks=[{"background": "MUS", "key": "A3"}],
    )
    assert apply_track_state(project).audio.ducks == []  # a regra cuja trilha não soa deixa de valer


# ---------- o aviso ----------


def test_the_warning_skips_the_effect_that_chose_to_hear_the_muted_track():
    with_choice = project_of([vocoder("A3", ignores=True)], tracks=muted("A3"))
    assert silenced_carrier_warnings(with_choice) == []
    without = project_of([vocoder("A3")], tracks=muted("A3"))
    assert len(silenced_carrier_warnings(without)) == 1


# ---------- a spec ----------


def test_the_dump_without_the_choice_has_no_field_and_the_signature_is_the_old_one():
    plain = parse_effect({"type": "vocoder"})
    assert "carrier_ignores_mute" not in plain.model_dump(mode="json")
    track_only = parse_effect({"type": "vocoder", "carrier_track": "MUS"})
    assert track_only.model_dump(mode="json")["carrier_track"] == "MUS"
    assert "carrier_ignores_mute" not in track_only.model_dump(mode="json")
    assert "carrier_ignores_mute" not in chain_signature([track_only])[0]
    chosen = parse_effect({"type": "vocoder", "carrier_track": "MUS", "carrier_ignores_mute": True})
    assert chosen.model_dump(mode="json")["carrier_ignores_mute"] is True
    assert chosen.hears_silenced_carrier() and not track_only.hears_silenced_carrier()
    assert not parse_effect({"type": "tremolo"}).hears_silenced_carrier()


def test_the_catalog_describes_the_choice_and_shows_it_only_with_a_chosen_track():
    from dmaker.domain.audio_effects import catalog_payload
    from dmaker.domain.audio_effects.base import SHOWN_WHEN_FILLED

    info = next(entry for entry in catalog_payload()["effects"] if entry["type"] == "vocoder")
    params = {param["name"]: param for param in info["parameters"]}
    choice = params["carrier_ignores_mute"]
    assert choice["kind"] == "boolean" and choice["default"] is False
    assert choice["label"] == "Ouvir a trilha mesmo muda"
    assert choice["shown_when"] == {"carrier_track": SHOWN_WHEN_FILLED}


# ---------- o pipeline: a mistura não muda, a passada prévia lê a visão ouvida ----------


def _recorded(tmp_path, monkeypatch, ignores: bool):
    """A prévia do áudio de um projeto cuja música está muda e cujo clipe (A1) tem um Vocoder ouvindo a música."""
    from .test_carrier_tracks_unit import build
    from .test_preview_audio import make_project as make_session

    effect = vocoder("MUS", ignores=ignores)
    tmp_path.mkdir(parents=True, exist_ok=True)
    project = make_session(
        tmp_path,
        sources={"cam1": {"src": "cam1.mp4"}},
        timeline=[{"type": "clip", "source": "cam1", "start": 0, "end": 5, "effects": [effect]}],
        audio={"normalize": "off", "music": {"src": "musica.mp3", "volume": 0.3, "ducking": False}},
        tracks={"MUS": {"muted": True}},
    )
    runner, _ = build(tmp_path, project, monkeypatch)
    return runner


def test_the_mix_commands_are_the_same_with_or_without_the_choice_and_only_the_choice_runs_the_pass(
    tmp_path, monkeypatch
):
    off = _recorded(tmp_path / "desligada", monkeypatch, ignores=False)
    on = _recorded(tmp_path / "ligada", monkeypatch, ignores=True)

    def joined(runner, folder) -> list[str]:
        # a pasta do teste e o nome do arquivo de cada pedaço (que leva a chave do item que ouve) saem da comparação
        return [
            re.sub(r"[0-9a-f]{8,}", "K", " ".join(command).replace(str(folder), "T"))
            for command in runner.commands
            if "carriers" not in " ".join(command)
        ]

    assert joined(off, tmp_path / "desligada") == joined(on, tmp_path / "ligada")
    assert not any("carriers" in " ".join(command) for command in off.commands)
    assert any("carriers" in " ".join(command) for command in on.commands)  # só a escolha lê a música muda


def test_the_preview_key_follows_the_file_of_a_muted_track_only_when_the_choice_is_on(tmp_path):
    from dmaker.media.ffmpeg import RecordingRunner

    from .test_auto_duck_early import builder_for

    def key_after(ignores: bool, content: bytes) -> str:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "musica.mp3").write_bytes(content)
        from .test_preview_audio import make_project as make_session

        project = make_session(
            tmp_path,
            sources={"cam1": {"src": "cam1.mp4"}},
            timeline=[
                {"type": "clip", "source": "cam1", "start": 0, "end": 5, "effects": [vocoder("MUS", ignores)]}
            ],
            audio={"music": {"src": "musica.mp3"}},
            tracks={"MUS": {"muted": True}},
        )
        return builder_for(tmp_path, RecordingRunner()).key(project)

    assert key_after(True, b"um som") != key_after(True, b"outro som, mais comprido")
    assert key_after(False, b"um som") == key_after(False, b"outro som, mais comprido")

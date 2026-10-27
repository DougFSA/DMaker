"""Etiqueta de procedência: o texto, a leitura, os trechos e os argumentos do ffmpeg que a gravam."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.filtergraph.dub import DubClip, dub_mix_command
from dmaker.filtergraph.dub_stems import StemOutputs, dub_stems_command
from dmaker.filtergraph.provenance import inherited_provenance_args, provenance_args
from dmaker.filtergraph.speech_edit import speech_splice_command
from dmaker.filtergraph.voice import narration_concat_command
from dmaker.filtergraph.voice_swap import voice_swap_command
from dmaker.voice.provenance import (
    MAX_SPANS,
    PROVENANCE_PREFIX,
    Provenance,
    combine_spans,
    describe_spans,
    merge_spans,
    parse_provenance,
    provenance_text,
)
from dmaker.voice.speech_edit import plan_splice

LABEL = "DMaker: voz gerada por IA (v1); trechos=33.10-34.42,50.00-52.30"


# ---------- o texto ----------


def test_the_label_is_readable_versioned_and_lists_the_spans():
    assert provenance_text([(33.1, 34.42), (50.0, 52.3)]) == LABEL


def test_the_whole_file_is_just_the_prefix():
    assert provenance_text() == PROVENANCE_PREFIX == "DMaker: voz gerada por IA (v1)"


def test_spans_that_leave_nothing_inside_the_file_declare_nothing():
    assert provenance_text([]) == ""
    assert provenance_text([(70.0, 75.0)], total=60.0) == ""  # a narração começa depois do fim do vídeo


def test_spans_are_cut_at_the_end_of_the_file():
    assert provenance_text([(58.0, 64.0)], total=60.0) == f"{PROVENANCE_PREFIX}; trechos=58.00-60.00"


def test_the_label_is_ascii_without_dashes_for_the_screen():
    text = provenance_text([(1.0, 2.0)])
    assert text.isascii() and "—" not in text


def test_merge_spans_sorts_fuses_overlaps_and_drops_empty_ones():
    merged = merge_spans([(10.0, 12.0), (1.0, 3.0), (2.5, 4.0), (7.0, 7.0), (12.0, 13.0)])
    assert merged == [(1.0, 4.0), (10.0, 13.0)]


def test_a_long_dubbing_has_its_nearest_spans_fused_to_keep_the_label_short():
    spans = [(index * 2.0, index * 2.0 + 1.0) for index in range(200)]  # 200 falas de 1 s, 1 s de intervalo
    merged = merge_spans(spans)
    assert len(merged) <= MAX_SPANS
    assert merged[0][0] == 0.0 and merged[-1][1] == 399.0  # continua cobrindo a primeira e a última fala
    assert len(provenance_text(spans)) < 1000


# ---------- a leitura ----------


def test_the_label_round_trips():
    assert parse_provenance({"comment": LABEL}) == Provenance(1, ((33.1, 34.42), (50.0, 52.3)))
    assert parse_provenance({"comment": provenance_text()}) == Provenance(1, ())


def test_the_tag_key_is_found_in_any_case_as_matroska_writes_it():
    assert parse_provenance({"COMMENT": LABEL, "ENCODER": "x"}) == Provenance(
        1, ((33.1, 34.42), (50.0, 52.3))
    )


@pytest.mark.parametrize("tags", [{}, {"comment": ""}, {"comment": "Gravado no celular"}, {"title": LABEL}])
def test_files_without_our_label_have_none(tags):
    assert parse_provenance(tags) is None


def test_a_newer_version_of_the_label_is_still_read():
    assert parse_provenance({"comment": "DMaker: voz gerada por IA (v2); trechos=1.00-2.00"}) == Provenance(
        2, ((1.0, 2.0),)
    )


def test_spans_are_described_in_portuguese():
    assert describe_spans([(33.1, 34.42), (50.0, 52.3)]) == "33,1 a 34,4 s; 50,0 a 52,3 s"


def test_combining_with_an_earlier_label_keeps_its_spans_or_the_whole_file():
    assert combine_spans(None, [(5.0, 6.0)]) == [(5.0, 6.0)]
    assert combine_spans(Provenance(1, ((1.0, 2.0),)), [(5.0, 6.0)]) == [(1.0, 2.0), (5.0, 6.0)]
    assert combine_spans(Provenance(1, ()), [(5.0, 6.0)]) is None  # já era o arquivo inteiro


# ---------- os argumentos ----------


def test_the_label_goes_in_the_standard_comment_key_with_no_special_movflags():
    args = provenance_args(LABEL)
    assert args == ["-metadata", f"comment={LABEL}"]
    assert "use_metadata_tags" not in " ".join(args)
    assert provenance_args("") == []


def test_a_new_timeline_clears_the_label_the_first_input_would_hand_down():
    assert inherited_provenance_args("") == ["-metadata", "comment="]
    assert inherited_provenance_args(LABEL) == ["-metadata", f"comment={LABEL}"]


def metadata(args: list[str]) -> list[str]:
    return [args[i + 1] for i, arg in enumerate(args) if arg == "-metadata"]


def test_narration_writes_the_label_before_the_output_and_nothing_without_it():
    parts = [(Path("a.wav"), 0.5)]
    labeled = narration_concat_command(parts, Path("n.m4a"), provenance=PROVENANCE_PREFIX).args
    assert metadata(labeled) == [f"comment={PROVENANCE_PREFIX}"] and labeled[-1] == "n.m4a"
    assert labeled.index("-metadata") < len(labeled) - 1
    assert metadata(narration_concat_command(parts, Path("n.m4a")).args) == []


CLIPS = [DubClip(Path("a.wav"), start=1.0), DubClip(Path("b.wav"), start=4.0)]


def test_dubbing_mix_writes_the_label_and_clears_an_inherited_one(tmp_path: Path):
    mix = dub_mix_command(
        Path("v.mp4"),
        Path("fundo.wav"),
        CLIPS,
        tmp_path / "o.mp4",
        tmp_path / "g.txt",
        30.0,
        True,
        provenance=LABEL,
    )
    assert metadata(mix.command.args) == [f"comment={LABEL}"] and mix.command.args[-1] == str(
        tmp_path / "o.mp4"
    )
    off = dub_mix_command(
        Path("v.mp4"), Path("fundo.wav"), CLIPS, tmp_path / "o.mp4", tmp_path / "g.txt", 30.0, True
    )
    assert metadata(off.command.args) == ["comment="]


def test_the_stems_label_only_the_dubbed_voice_track():
    outputs = StemOutputs(Path("t/voz-dublada.wav"), Path("t/fundo.wav"), Path("t/voz-original.wav"))
    args = dub_stems_command(
        Path("bg.wav"), Path("vo.wav"), CLIPS, outputs, Path("g.txt"), 30.0, provenance=PROVENANCE_PREFIX
    ).command.args
    assert metadata(args) == [f"comment={PROVENANCE_PREFIX}"]
    assert args.index("-metadata") == args.index(str(outputs.voice_dubbed)) - 2  # logo antes da trilha da voz
    plain = dub_stems_command(
        Path("bg.wav"), Path("vo.wav"), CLIPS, outputs, Path("g.txt"), 30.0
    ).command.args
    assert metadata(plain) == []


def test_speech_splice_writes_the_label_and_leaves_the_inherited_one_alone(tmp_path: Path):
    plan = plan_splice(11.7, 12.9, "de João e Maria", "de Pedro e Maria", 0.6, 1.1)
    command = speech_splice_command(
        tmp_path / "v.mp4",
        tmp_path / "bg.wav",
        tmp_path / "f.wav",
        tmp_path / "o.mp4",
        plan,
        0.0,
        has_video=True,
        provenance=LABEL,
    )
    assert metadata(command.args) == [f"comment={LABEL}"]
    off = speech_splice_command(
        tmp_path / "v.mp4",
        tmp_path / "bg.wav",
        tmp_path / "f.wav",
        tmp_path / "o.mp4",
        plan,
        0.0,
        has_video=True,
    )
    assert (
        metadata(off.args) == []
    )  # a correção mantém a linha do tempo: a etiqueta que o original já tinha continua valendo


def test_voice_swap_writes_the_label_or_clears_the_inherited_one(tmp_path: Path):
    kwargs = {"has_video": True}
    labeled = voice_swap_command(
        tmp_path / "v.mp4",
        tmp_path / "voz.wav",
        tmp_path / "fundo.wav",
        tmp_path / "o.mp4",
        30.0,
        0.0,
        provenance=LABEL,
        **kwargs,
    )
    assert metadata(labeled.args) == [f"comment={LABEL}"]
    off = voice_swap_command(
        tmp_path / "v.mp4",
        tmp_path / "voz.wav",
        tmp_path / "fundo.wav",
        tmp_path / "o.mp4",
        30.0,
        0.0,
        **kwargs,
    )
    assert metadata(off.args) == ["comment="]


# ---------- a leitura pelo probe ----------


def test_probe_exposes_the_container_tags(monkeypatch, tmp_path: Path):
    from dmaker.media import probe as probe_module

    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    monkeypatch.setattr(
        probe_module,
        "probe_json",
        lambda path: {
            "streams": [{"codec_type": "audio", "sample_rate": "48000", "channels": 2}],
            "format": {"duration": "10", "tags": {"comment": LABEL, "encoder": "Lavf"}},
        },
    )
    probe_module._probe_cached.cache_clear()  # noqa: SLF001

    info = probe_module.probe(media)

    assert info.format_tags == {"comment": LABEL, "encoder": "Lavf"}
    assert parse_provenance(info.format_tags) == Provenance(1, ((33.1, 34.42), (50.0, 52.3)))
    assert hash(info) is not None  # o dict de tags fica fora do hash e da comparação

"""Macros de áudio: o formato, as pastas, a migração do DMK-54, salvar a cadeia de um item e aplicar a uma pasta de arquivos.

Sem ffmpeg: o render de cada arquivo entra por um dublê (`MacroFileRenderer`), então a retomada, a trava e o relatório se
provam rápido. O som de verdade, com tom, ruído e fala sintética, está em `test_macros_integration.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dmaker import config, mcp_server
from dmaker.cli import app
from dmaker.domain.audio_effects import (
    EFFECT_PRESETS,
    EffectPreset,
    catalog_payload,
    get_effect_preset,
    list_user_presets,
    parse_effect,
    remove_user_preset,
    save_user_preset,
)
from dmaker.domain.audio_effects.macro_output import clean_output, output_choices
from dmaker.domain.audio_effects.user_presets import macros_dir, migrate_legacy_presets
from dmaker.domain.effect_edits import apply_effect_op
from dmaker.domain.spec import Project
from dmaker.pipeline import macro_run
from dmaker.pipeline.filelock import FileLock
from dmaker.pipeline.macro_run import (
    STATE_FOLDER,
    STATE_NAME,
    FileOutcome,
    MacroRunBusyError,
    MacroRunError,
    MacroRunService,
    expand_inputs,
    plan_macro_run,
    unique_names,
)
from dmaker.pipeline.macros import save_chain_as_macro
from dmaker.ui import server

from . import guard

runner = CliRunner()

BUILTIN_MACROS = {"mp3_standard", "ends_fade", "clean_narration", "clean_phone_recording"}


def project_with_chain(*effects: dict, brand: str | None = None, name: str = "macro-teste") -> Project:
    data = {
        "name": name,
        "timeline": [],
        "output": {"preset": "audio/wav"},
        "audio": {
            "normalize": "off",
            "voiceover": [{"src": "a.wav", "effects": list(effects)}, {"src": "b.wav"}],
        },
    }
    if brand:
        data["brand"] = brand
    return Project.model_validate(data)


# ---------- as macros embutidas ----------


def test_the_four_builtin_macros_are_in_the_catalog_with_valid_effects():
    assert BUILTIN_MACROS <= set(EFFECT_PRESETS)  # `<=`: as outras famílias registram as delas no mesmo lugar
    in_catalog = {preset["id"]: preset for preset in catalog_payload()["presets"]}
    for identifier in BUILTIN_MACROS:
        entry = in_catalog[identifier]
        assert entry["origin"] == "builtin" and entry["scope"] == "builtin"
        for effect in entry["effects"]:
            parse_effect(effect)  # cada efeito da macro é um efeito válido da spec
    assert in_catalog["mp3_standard"]["output"] == {"preset": "audio/mp3"}
    assert "output" not in in_catalog["clean_narration"]  # só entra no catálogo quando a macro tem saída


def test_the_builtin_recipes_follow_the_ones_the_cards_describe():
    narration = [effect["type"] for effect in get_effect_preset("clean_narration").effects]
    assert narration == ["highpass", "noise_reduction", "compressor", "loudness_normalize", "limiter"]
    phone = get_effect_preset("clean_phone_recording").effects
    assert [effect["type"] for effect in phone] == [
        "highpass",
        "click_removal",
        "noise_reduction",
        "noise_gate",
        "normalize",
    ]
    assert phone[0]["frequency_hz"] == 80 and phone[2]["reduction_db"] == 12
    assert (phone[2]["sensitivity"], phone[2]["smoothing_bands"]) == (6, 3)
    assert [effect["type"] for effect in get_effect_preset("ends_fade").effects] == ["fade_in", "fade_out"]
    assert [effect["type"] for effect in get_effect_preset("mp3_standard").effects] == ["normalize"]


def test_a_builtin_macro_with_a_noise_gate_is_refused_on_the_master_and_accepted_on_a_voice():
    from dmaker.domain.edits import EditError

    project = project_with_chain()
    done = apply_effect_op(
        project, {"action": "preset", "target": "audio.voiceover.1", "preset": "clean_phone_recording"}
    )
    assert [e.type for e in done.audio.voiceover[1].effects][0] == "highpass"
    with pytest.raises(EditError, match="não vale"):
        apply_effect_op(
            project, {"action": "preset", "target": "audio.master", "preset": "clean_phone_recording"}
        )


def test_applying_a_macro_to_an_item_ignores_the_output_and_keeps_the_chain_editable():
    project = project_with_chain()
    done = apply_effect_op(
        project, {"action": "preset", "target": "audio.voiceover.1", "preset": "mp3_standard"}
    )
    assert [e.type for e in done.audio.voiceover[1].effects] == ["normalize"]
    assert done.output.preset == project.output.preset  # a saída da macro não muda o projeto


# ---------- a saída da macro ----------


def test_the_output_is_validated_when_saving_and_not_only_when_applying():
    assert clean_output({"preset": "mp3", "bitrate_k": 128}) == {"preset": "audio/mp3", "bitrate_k": 128}
    assert clean_output(None) is None and clean_output({}) is None
    with pytest.raises(ValueError, match="profundidade|bit"):
        clean_output({"preset": "audio/mp3", "bit_depth": 24})
    with pytest.raises(ValueError, match="formato de áudio"):
        clean_output({"preset": "instagram/reels"})
    with pytest.raises(ValueError, match="desconhecido"):
        clean_output({"preset": "audio/wav", "volume": 3})
    with pytest.raises(ValueError, match="objeto"):
        clean_output("mp3")
    assert output_choices({"preset": "audio/mp3"}) is None
    assert output_choices({"preset": "audio/mp3", "bitrate_k": 96}).bitrate_k == 96


# ---------- as pastas de macros do usuário ----------


def test_a_saved_macro_is_one_json_in_the_global_folder_and_carries_its_output():
    saved = save_user_preset(
        "Limpa e MP3",
        [{"type": "highpass", "frequency_hz": 70, "start": 1, "enabled": False}],
        "uma frase",
        output={"preset": "audio/mp3", "bitrate_k": 128},
    )
    assert saved.id == "limpa-e-mp3" and saved.scope == "global" and saved.origin == "user"
    path = config.MACROS_DIR / "limpa-e-mp3.json"
    assert path.is_file() and config.MACROS_DIR == config.DATA_DIR / "assets" / "macros"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["output"] == {"preset": "audio/mp3", "bitrate_k": 128}
    assert "start" not in on_disk["effects"][0] and "enabled" not in on_disk["effects"][0]
    in_catalog = next(p for p in catalog_payload()["presets"] if p["id"] == "limpa-e-mp3")
    assert in_catalog["output"]["bitrate_k"] == 128 and in_catalog["scope"] == "global"
    assert get_effect_preset("limpa-e-mp3").output == {"preset": "audio/mp3", "bitrate_k": 128}


def test_a_brand_macro_lives_in_the_brand_folder_and_wins_over_the_global_one_with_the_same_id():
    save_user_preset("Voz", [{"type": "highpass", "frequency_hz": 80}])
    save_user_preset("Voz", [{"type": "highpass", "frequency_hz": 120}], brand="acme")
    assert (config.BRAND_DATA_DIR / "acme" / "macros" / "voz.json").is_file()
    assert macros_dir("acme") == config.DATA_DIR / "assets" / "brands" / "acme" / "macros"
    assert get_effect_preset("voz").effects[0]["frequency_hz"] == 80  # sem a marca, vale a global
    here = get_effect_preset("voz", "acme")
    assert here.effects[0]["frequency_hz"] == 120 and here.scope == "brand:acme"
    user = [p for p in catalog_payload(brand="acme")["presets"] if p["origin"] == "user"]
    assert [(p["id"], p["scope"]) for p in user] == [("voz", "brand:acme")]  # uma entrada só, a da marca
    assert [p.scope for p in list_user_presets("outra")] == ["global"]
    assert remove_user_preset("voz", "acme").scope == "brand:acme"
    assert get_effect_preset("voz", "acme").scope == "global"  # sobrou a global
    with pytest.raises(ValueError, match="marca inválido"):
        save_user_preset("X", [{"type": "notch"}], brand="../fora")


def test_a_macro_cannot_take_the_name_of_a_builtin_one_in_any_spelling():
    with pytest.raises(ValueError, match="embutida"):
        save_user_preset("Limpar narração", [{"type": "notch"}])
    with pytest.raises(ValueError, match="embutida"):
        save_user_preset("Telephone", [{"type": "notch"}])
    with pytest.raises(ValueError, match="embutida"):
        remove_user_preset("clean_narration")
    with pytest.raises(ValueError, match="desconhecida"):
        remove_user_preset("../assets")  # o id nunca sai da pasta de macros


# ---------- a migração do effect-presets.json (DMK-54) ----------


def legacy_file(entries: dict) -> Path:
    config.EFFECT_PRESETS_FILE.write_text(
        json.dumps({"version": 1, "presets": entries}, ensure_ascii=False), encoding="utf-8"
    )
    return config.EFFECT_PRESETS_FILE


def test_the_old_presets_file_becomes_global_macros_and_is_renamed_never_deleted():
    legacy = legacy_file(
        {
            "minha-voz": {"label": "Minha voz", "summary": "do DMK-54", "effects": [{"type": "notch"}]},
            "ronco": {"label": "Ronco", "summary": "", "effects": [{"type": "highpass", "frequency_hz": 70}]},
        }
    )
    original = legacy.read_text(encoding="utf-8")
    assert [p.id for p in list_user_presets()] == ["minha-voz", "ronco"]  # o primeiro acesso migra
    assert not legacy.exists()
    kept = legacy.with_name("effect-presets.json.importado")
    assert kept.read_text(encoding="utf-8") == original  # o conteúdo continua inteiro, só mudou de nome
    macro = json.loads((config.MACROS_DIR / "minha-voz.json").read_text(encoding="utf-8"))
    assert macro["label"] == "Minha voz" and macro["summary"] == "do DMK-54"
    assert get_effect_preset("ronco").scope == "global"
    assert migrate_legacy_presets() == []  # repetir não faz nada


def test_the_migration_does_not_overwrite_a_macro_that_already_exists_and_never_reuses_the_kept_name():
    save_user_preset("Minha voz", [{"type": "highpass", "frequency_hz": 100}])
    legacy_file({"minha-voz": {"label": "Antiga", "effects": [{"type": "notch"}]}})
    assert migrate_legacy_presets() == []  # já existe uma macro de mesmo id: a nova (editada) ganha
    assert get_effect_preset("minha-voz").label == "Minha voz"
    legacy_file({"outra": {"label": "Outra", "effects": [{"type": "notch"}]}})  # um segundo arquivo antigo
    assert migrate_legacy_presets() == ["outra"]
    names = sorted(path.name for path in config.DATA_DIR.glob("effect-presets*"))
    assert names == ["effect-presets.json.importado", "effect-presets.json.importado.2"]


def test_an_unreadable_old_file_is_left_where_it_is_and_hides_nothing():
    config.EFFECT_PRESETS_FILE.write_text("{ isto não é json", encoding="utf-8")
    saved = save_user_preset("Nova", [{"type": "notch"}])
    assert saved.id == "nova" and [p.id for p in list_user_presets()] == ["nova"]
    assert config.EFFECT_PRESETS_FILE.read_text(encoding="utf-8") == "{ isto não é json"


def test_saving_and_removing_also_trigger_the_migration():
    legacy_file({"velha": {"label": "Velha", "effects": [{"type": "notch"}]}})
    assert remove_user_preset("velha").label == "Velha"
    assert not config.EFFECT_PRESETS_FILE.exists() and not (config.MACROS_DIR / "velha.json").exists()


# ---------- o guard dos testes ----------


def test_the_test_guard_refuses_writes_to_the_real_macro_folders_and_the_old_presets_file(tmp_path):
    protected = guard.Guard(tmp_path, models_are_real=False)
    for path in (
        tmp_path / "assets" / "macros" / "x.json",
        tmp_path / "assets" / "macros",
        tmp_path / "assets" / "brands" / "acme" / "macros" / "x.json",
        tmp_path / "assets" / "brands" / "acme" / "macros",
        tmp_path / "effect-presets.json",
        tmp_path / "effect-presets.json.importado",
    ):
        assert protected.is_protected(guard._key(path)), path
    for path in (
        tmp_path / "assets" / "brands" / "acme" / "brand.json",
        tmp_path / "assets" / "fonts" / "x.ttf",
    ):
        assert not protected.is_protected(guard._key(path)), path


def test_the_macro_folders_are_in_the_data_dir_the_suite_redirects():
    assert config.MACROS_DIR.is_relative_to(config.DATA_DIR) and config.BRAND_DATA_DIR.is_relative_to(
        config.DATA_DIR
    )
    assert not config.MACROS_DIR.is_relative_to(config.ROOT)  # nunca a pasta de macros de quem usa o editor


# ---------- salvar a cadeia de um item ----------


def test_a_chain_saved_from_one_item_and_applied_to_another_gives_the_same_effect_list():
    source = project_with_chain(
        {"type": "highpass", "frequency_hz": 85, "slope_db": 24, "start": 2.0, "end": 4.0},
        {"type": "noise_gate", "threshold_db": -45, "enabled": False},
        {"type": "loudness_normalize", "target_db": -18},
    )
    macro = save_chain_as_macro(source, "audio.voiceover.0", "Minha cadeia", summary="de um item")
    assert [e["type"] for e in macro.effects] == ["highpass", "noise_gate", "loudness_normalize"]
    done = apply_effect_op(source, {"action": "preset", "target": "audio.voiceover.1", "preset": macro.id})
    applied = [effect.model_dump(mode="json") for effect in done.audio.voiceover[1].effects]
    saved = [dict(effect) for effect in macro.effects]
    # a macro leva o ajuste, e o intervalo e o bypass (do item de origem) ficam de fora
    strip = ("start", "end", "enabled")
    assert [{k: v for k, v in e.items() if k not in strip} for e in applied] == [
        {k: v for k, v in e.items() if k not in strip} for e in saved
    ]
    assert all(e["enabled"] is True and e["start"] is None and e["end"] is None for e in applied)


def test_saving_a_chain_by_brand_needs_a_brand_and_refuses_an_empty_item():
    source = project_with_chain({"type": "highpass", "frequency_hz": 85}, brand="acme")
    macro = save_chain_as_macro(source, "audio.voiceover.0", "Da marca", scope="brand")
    assert (
        macro.scope == "brand:acme"
        and (config.BRAND_DATA_DIR / "acme" / "macros" / "da-marca.json").is_file()
    )
    other = apply_effect_op(source, {"action": "preset", "target": "audio.voiceover.1", "preset": "da-marca"})
    assert [e.type for e in other.audio.voiceover[1].effects] == [
        "highpass"
    ]  # o projeto é da marca: acha a macro
    without_brand = project_with_chain({"type": "notch"}, name="sem-marca")
    from dmaker.domain.edits import EditError

    with pytest.raises(ValueError, match="não tem marca"):
        save_chain_as_macro(without_brand, "audio.voiceover.0", "X", scope="brand")
    with pytest.raises(ValueError, match="não tem efeitos"):
        save_chain_as_macro(source, "audio.voiceover.1", "Vazia")
    with pytest.raises(ValueError, match="escopo"):
        save_chain_as_macro(source, "audio.voiceover.0", "X", scope="mundo")
    with pytest.raises(
        EditError, match="da-marca"
    ):  # outro projeto, de outra marca (ou sem marca), não vê a da marca
        apply_effect_op(
            without_brand, {"action": "preset", "target": "audio.voiceover.0", "preset": "da-marca"}
        )


# ---------- o plano: entradas, nomes e formato ----------


def make_files(folder: Path, names: list[str]) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / name for name in names]
    for path in paths:
        path.write_bytes(path.name.encode("utf-8"))
    return paths


def test_a_folder_gives_its_audio_files_in_name_order_and_ignores_the_rest(tmp_path):
    make_files(tmp_path / "in", ["b.WAV", "a.mp3", "capa.png", "c.m4a", "d.txt"])
    (tmp_path / "in" / "sub").mkdir()
    (tmp_path / "in" / "sub" / "z.wav").write_bytes(b"z")  # as subpastas não entram
    assert [p.name for p in expand_inputs([tmp_path / "in"])] == ["a.mp3", "b.WAV", "c.m4a"]
    explicit = expand_inputs(
        [tmp_path / "in" / "capa.png", tmp_path / "in" / "a.mp3", tmp_path / "in" / "a.mp3"]
    )
    assert [p.name for p in explicit] == [
        "capa.png",
        "a.mp3",
    ]  # um arquivo dado por nome vale; repetido sai uma vez
    with pytest.raises(MacroRunError, match="não encontrei"):
        expand_inputs([tmp_path / "nao-existe"])
    (tmp_path / "vazia").mkdir()
    with pytest.raises(MacroRunError, match="não tem arquivos de áudio"):
        expand_inputs([tmp_path / "vazia"])
    with pytest.raises(MacroRunError, match="informe"):
        expand_inputs([])


def test_output_names_never_repeat_even_ignoring_case():
    assert unique_names(["voz", "Voz", "voz", "outra"]) == ["voz", "Voz-2", "voz-3", "outra"]


def test_the_plan_takes_the_format_from_the_request_or_the_macro_and_refuses_when_neither_has_one(tmp_path):
    make_files(tmp_path / "in", ["a.wav"])
    clean = get_effect_preset("clean_narration")
    with pytest.raises(MacroRunError, match="não traz formato"):
        plan_macro_run(clean, [tmp_path / "in"], tmp_path / "out")
    assert plan_macro_run(clean, [tmp_path / "in"], tmp_path / "out", "flac").preset.id == "audio/flac"
    mp3 = plan_macro_run(get_effect_preset("mp3_standard"), [tmp_path / "in"], tmp_path / "out")
    assert mp3.preset.id == "audio/mp3" and mp3.output_path(0) == (tmp_path / "out" / "a.mp3").resolve()
    with pytest.raises(MacroRunError, match="desconhecido"):
        plan_macro_run(clean, [tmp_path / "in"], tmp_path / "out", "ogg2")
    with pytest.raises(MacroRunError, match="não tem efeitos"):
        plan_macro_run(EffectPreset("x", "X", "", ()), [tmp_path / "in"], tmp_path / "out", "wav")


def test_the_encoding_choices_of_the_macro_only_apply_to_its_own_format(tmp_path):
    make_files(tmp_path / "in", ["a.wav"])
    own = EffectPreset(
        "m", "M", "", ({"type": "normalize"},), output={"preset": "audio/mp3", "bitrate_k": 96}
    )
    assert plan_macro_run(own, [tmp_path / "in"], tmp_path / "out").choices.bitrate_k == 96
    assert plan_macro_run(own, [tmp_path / "in"], tmp_path / "out", "mp3").choices.bitrate_k == 96
    assert plan_macro_run(own, [tmp_path / "in"], tmp_path / "out", "flac").choices is None


def test_the_output_can_never_land_on_top_of_an_input_file(tmp_path):
    make_files(tmp_path / "in", ["a.wav", "b.mp3"])
    macro = get_effect_preset("clean_narration")
    with pytest.raises(MacroRunError, match="o original não é sobrescrito"):
        plan_macro_run(macro, [tmp_path / "in"], tmp_path / "in", "wav")  # a.wav -> a.wav
    plan = plan_macro_run(
        macro, [tmp_path / "in"], tmp_path / "in", "flac"
    )  # formato diferente: nomes diferentes
    assert [p.name for p in plan.outputs()] == ["a.flac", "b.flac"]


# ---------- o job: 20 arquivos, o mesmo tratamento, a retomada ----------


class Crash(BaseException):
    """A queda do processo: não é um erro do arquivo, e nada do serviço a captura (como um kill no meio)."""


class FakeRenderer:
    """Grava `parcial` com o conteúdo do original e devolve; guarda o que recebeu para o teste conferir."""

    def __init__(self, fail_on: str | None = None, crash_on: str | None = None) -> None:
        self.calls: list[str] = []
        self.effects: list[tuple] = []
        self.targets: list[Path] = []
        self.fail_on, self.crash_on = fail_on, crash_on

    def render(self, source, effects, out, preset, choices, *, sink, log):
        self.calls.append(source.name)
        self.effects.append(tuple(json.dumps(e, sort_keys=True) for e in effects))
        self.targets.append(out)
        out.write_bytes(b"meio")
        if source.name == self.crash_on:
            raise Crash
        if source.name == self.fail_on:
            raise RuntimeError("arquivo ilegível")
        out.write_bytes(b"tratado:" + source.read_bytes())
        return FileOutcome(out, 1.5, 0.001, [])


NAMES_20 = [f"fala-{number:02d}.wav" for number in range(1, 21)]


@pytest.fixture
def twenty(tmp_path):
    make_files(tmp_path / "in", NAMES_20)
    macro = get_effect_preset("clean_narration")
    return macro, tmp_path / "in", tmp_path / "out"


def test_twenty_files_give_twenty_outputs_with_the_same_chain_and_a_report(twenty):
    macro, folder, out = twenty
    renderer = FakeRenderer()
    report = MacroRunService(renderer).run(plan_macro_run(macro, [folder], out, "wav"))
    assert (
        len(renderer.calls) == 20 and report.done == 20 and report.failed == 0 and report.status == "finished"
    )
    assert len(set(renderer.effects)) == 1  # a mesma cadeia para os 20
    assert tuple(json.dumps(dict(e), sort_keys=True) for e in macro.effects) == renderer.effects[0]
    for name in NAMES_20:
        result = out / name
        assert result.read_bytes() == b"tratado:" + name.encode("utf-8")
    assert not list(out.glob("*.parcial.*"))  # o arquivo final só aparece inteiro
    assert (out / "relatorio.txt").is_file() and "20 de 20 arquivo(s) pronto(s)" in report.to_text()
    assert report.summary() == "20 de 20 arquivo(s) pronto(s)"
    assert (out / STATE_FOLDER / f"{STATE_NAME}.json").is_file()  # o estado fica na pasta de saída


def test_a_crash_at_file_eight_then_resume_runs_only_the_files_that_were_missing(twenty):
    macro, folder, out = twenty
    plan = plan_macro_run(macro, [folder], out, "wav")
    first = FakeRenderer(crash_on="fala-08.wav")
    with pytest.raises(Crash):
        MacroRunService(first).run(plan)
    assert first.calls == NAMES_20[:8]
    assert (out / "fala-08.parcial.wav").exists()  # a queda deixou o arquivo pela metade...
    assert not (out / "fala-08.wav").exists()  # ...e ele nunca passou por pronto
    state = MacroRunService(first).store(out).load(STATE_NAME)
    assert [row.state for row in state.rows[:8]] == ["done"] * 7 + ["running"]
    assert not MacroRunService(first).active(out)  # a trava caiu com o processo: ninguém mais "roda"

    second = FakeRenderer()
    report = MacroRunService(second).run(plan, resume=True)
    assert second.calls == NAMES_20[7:]  # só os 13 que faltavam, o oitavo refeito
    assert report.done == 20 and report.status == "finished"
    assert not list(out.glob("*.parcial.*"))
    assert (out / "fala-08.wav").read_bytes() == b"tratado:fala-08.wav"
    # sem `resume`, tudo é refeito
    third = FakeRenderer()
    MacroRunService(third).run(plan)
    assert third.calls == NAMES_20


def test_a_failing_file_does_not_stop_the_others_and_resume_redoes_only_that_one(twenty):
    macro, folder, out = twenty
    plan = plan_macro_run(macro, [folder], out, "wav")
    first = FakeRenderer(fail_on="fala-05.wav")
    report = MacroRunService(first).run(plan)
    assert report.done == 19 and report.failed == 1 and len(first.calls) == 20
    failed = next(row for row in report.rows if row.state == "failed")
    assert failed.title == "fala-05.wav" and "arquivo ilegível" in failed.error
    assert "fala-05.wav" in report.to_text() and "falhou" in report.summary()
    assert not (out / "fala-05.wav").exists() and not list(out.glob("*.parcial.*"))
    second = FakeRenderer()
    again = MacroRunService(second).run(plan, resume=True)
    assert second.calls == ["fala-05.wav"] and again.done == 20


def test_resume_redoes_what_changed_since_the_last_run(twenty):
    macro, folder, out = twenty
    plan = plan_macro_run(macro, [folder], out, "wav")
    MacroRunService(FakeRenderer()).run(plan)
    (folder / "fala-03.wav").write_bytes(b"gravei de novo, bem maior")  # o original mudou
    (out / "fala-04.wav").unlink()  # o resultado sumiu
    changed = FakeRenderer()
    MacroRunService(changed).run(plan_macro_run(macro, [folder], out, "wav"), resume=True)
    assert sorted(changed.calls) == ["fala-03.wav", "fala-04.wav"]
    other = EffectPreset("outra", "Outra", "", ({"type": "normalize"},))  # outra cadeia: refaz todos
    redone = FakeRenderer()
    MacroRunService(redone).run(plan_macro_run(other, [folder], out, "wav"), resume=True)
    assert len(redone.calls) == 20
    other_format = FakeRenderer()  # outro formato: nomes novos, tudo a fazer
    MacroRunService(other_format).run(plan_macro_run(other, [folder], out, "flac"), resume=True)
    assert len(other_format.calls) == 20


def test_pausing_stops_after_the_current_file_and_resume_finishes(twenty):
    macro, folder, out = twenty
    plan = plan_macro_run(macro, [folder], out, "wav")
    first = FakeRenderer()
    logged: list[str] = []

    def stop() -> bool:
        return len(first.calls) >= 3

    report = MacroRunService(first).run(plan, should_stop=stop, log=logged.append)
    assert first.calls == NAMES_20[:3] and report.status == "paused" and report.waiting == 17
    assert any("pausado" in line.lower() for line in logged)
    second = FakeRenderer()
    assert MacroRunService(second).run(plan, resume=True).done == 20 and second.calls == NAMES_20[3:]


def test_two_runs_on_the_same_output_folder_do_not_overlap(twenty):
    macro, folder, out = twenty
    plan = plan_macro_run(macro, [folder], out, "wav")
    service = MacroRunService(FakeRenderer())
    other = FileLock(service.store(out).lock_path(STATE_NAME))
    assert other.try_acquire()
    try:
        assert service.active(out)
        with pytest.raises(MacroRunBusyError, match="já há um tratamento"):
            service.run(plan)
    finally:
        other.release()
    assert not service.active(out)


def test_the_state_report_reads_a_folder_that_was_interrupted(twenty):
    macro, folder, out = twenty
    plan = plan_macro_run(macro, [folder], out, "wav")
    with pytest.raises(Crash):
        MacroRunService(FakeRenderer(crash_on="fala-02.wav")).run(plan)
    report = MacroRunService().report(out)
    assert report.status == "paused" and report.done == 1 and report.waiting == 19
    assert report.rows[0].source.endswith("fala-01.wav")


def test_the_planned_outputs_skip_what_the_state_already_has_done_when_resuming(twenty):
    macro, folder, out = twenty
    plan = plan_macro_run(macro, [folder], out, "wav")
    service = MacroRunService(FakeRenderer(crash_on="fala-04.wav"))
    with pytest.raises(Crash):
        service.run(plan)
    assert len(service.planned_outputs(plan, resume=False)) == 20
    assert [p.name for p in service.planned_outputs(plan, resume=True)] == NAMES_20[3:]


# ---------- os adaptadores ----------


@pytest.fixture
def fake_renderer(monkeypatch):
    renderer = FakeRenderer()
    monkeypatch.setattr(macro_run, "PipelineFileRenderer", lambda *args, **kwargs: renderer)
    return renderer


def test_the_mcp_applies_a_macro_in_a_job_and_the_status_reports_each_file(tmp_path, fake_renderer):
    make_files(tmp_path / "in", ["um.wav", "dois.wav", "tres.wav"])
    out = tmp_path / "out"
    started = mcp_server.apply_macro(
        "clean_narration", [str(tmp_path / "in")], str(out), format="mp3", wait_seconds=30
    )
    assert started["job_id"] and started["files"] == 3 and started["status"] == "done"
    assert started["result"]["done"] == 3
    status = mcp_server.job_status(started["job_id"])
    assert status["status"] == "done" and [row["state"] for row in status["result"]["rows"]] == ["done"] * 3
    assert sorted(path.name for path in out.glob("*.mp3")) == ["dois.mp3", "tres.mp3", "um.mp3"]
    # retomar uma pasta que já está pronta não refaz nada
    fake_renderer.calls.clear()
    again = mcp_server.apply_macro(
        "clean_narration", [str(tmp_path / "in")], str(out), format="mp3", resume=True, wait_seconds=30
    )
    assert again["result"]["done"] == 3 and fake_renderer.calls == []


def test_the_mcp_refuses_a_bad_request_with_the_reason(tmp_path, fake_renderer):
    from mcp.server.mcpserver.exceptions import ToolError

    make_files(tmp_path / "in", ["um.wav"])
    with pytest.raises(ToolError, match="não traz formato"):
        mcp_server.apply_macro("clean_narration", [str(tmp_path / "in")], str(tmp_path / "out"))
    with pytest.raises(ToolError, match="desconhecida"):
        mcp_server.apply_macro("nao-existe", [str(tmp_path / "in")], str(tmp_path / "out"), format="mp3")
    with pytest.raises(ToolError, match="o original não é sobrescrito"):
        mcp_server.apply_macro("clean_narration", [str(tmp_path / "in")], str(tmp_path / "in"), format="wav")


def test_the_mcp_manages_the_macros_and_saves_the_chain_of_a_project_item():
    from mcp.server.mcpserver.exceptions import ToolError

    saved = mcp_server.audio_effect_presets(
        "save", label="Pela ferramenta", effects=[{"type": "notch"}], output={"preset": "flac"}
    )
    assert saved["id"] == "pela-ferramenta" and saved["output"] == {"preset": "audio/flac"}
    assert [p["id"] for p in mcp_server.audio_effect_presets("list")["presets"]] == ["pela-ferramenta"]
    assert mcp_server.audio_effect_presets("show", id="clean_narration")["origin"] == "builtin"
    project_with_chain({"type": "highpass", "frequency_hz": 90}, name="mcp-macro").save(
        config.PROJECTS_DIR / "mcp-macro" / "spec.json"
    )
    from_item = mcp_server.audio_effect_presets(
        "save", label="Do item", project="mcp-macro", target="audio.voiceover.0"
    )
    assert [e["type"] for e in from_item["effects"]] == ["highpass"]
    with pytest.raises(ToolError, match="project"):
        mcp_server.audio_effect_presets("save", label="X", target="audio.voiceover.0")
    assert mcp_server.audio_effect_presets("remove", id="do-item")["id"] == "do-item"
    with pytest.raises(ToolError, match="ação desconhecida"):
        mcp_server.audio_effect_presets("apagar-tudo")


def test_the_new_mcp_tool_is_outside_the_agent_kits_with_a_reason_and_under_the_overwrite_watch():
    from dmaker.agent.kits import EXCLUDED_TOOLS
    from dmaker.agent.safety import DEFAULT_OUTPUTS, EXACT_OUTPUTS, OVERWRITES_EXISTING_OUTPUT

    assert EXCLUDED_TOOLS["apply_macro"].strip()
    assert "apply_macro" in OVERWRITES_EXISTING_OUTPUT and "apply_macro" in EXACT_OUTPUTS
    assert "apply_macro" in DEFAULT_OUTPUTS


def test_the_agent_asks_before_a_macro_run_overwrites_files(tmp_path):
    from dmaker.agent.safety import ApproveAll, ToolGate

    make_files(tmp_path / "in", ["um.wav", "dois.wav"])
    target = str((tmp_path / "out" / "um.mp3").resolve())
    arguments = {
        "macro": "clean_narration",
        "inputs": [str(tmp_path / "in")],
        "out_dir": str(tmp_path / "out"),
        "format": "mp3",
    }

    def gate(existing: set[str]) -> ToolGate:
        return ToolGate(schemas={}, policy=ApproveAll(), exists=lambda path: path in existing)

    asked = gate({target}).confirmations("apply_macro", arguments)
    assert [r.question for r in asked] == [f"O arquivo '{target}' já existe. Posso sobrescrevê-lo?"]
    assert gate(set()).confirmations("apply_macro", arguments) == []
    # um pedido que o servidor recusa (macro que não existe) não grava nada: não há o que perguntar
    assert gate({target}).confirmations("apply_macro", {**arguments, "macro": "nao-existe"}) == []


def test_the_cli_manages_macros_and_runs_one_on_a_folder(tmp_path, fake_renderer):
    listed = runner.invoke(app, ["audio", "macro", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert BUILTIN_MACROS <= {p["id"] for p in json.loads(listed.output)["presets"]}
    shown = runner.invoke(app, ["audio", "macro", "show", "clean_narration"])
    assert shown.exit_code == 0 and "loudness_normalize" in shown.output and "Limpar narração" in shown.output
    saved = runner.invoke(
        app,
        [
            "audio",
            "macro",
            "save",
            "Da linha",
            "-e",
            '{"type": "highpass", "frequency_hz": 80}',
            "--format",
            "mp3",
        ],
    )
    assert saved.exit_code == 0, saved.output
    assert get_effect_preset("da-linha").output == {"preset": "audio/mp3"}
    spec = project_with_chain({"type": "notch", "frequency_hz": 60}).save(tmp_path / "spec.json")
    from_item = runner.invoke(
        app,
        [
            "audio",
            "macro",
            "save",
            "Do projeto",
            "--from-project",
            str(spec),
            "--target",
            "audio.voiceover.0",
        ],
    )
    assert from_item.exit_code == 0, from_item.output
    assert get_effect_preset("do-projeto").effects[0]["type"] == "notch"
    assert (
        runner.invoke(app, ["audio", "macro", "save", "Só o alvo", "--target", "audio.voiceover.0"]).exit_code
        == 1
    )

    make_files(tmp_path / "in", ["x.wav", "y.wav"])
    run = runner.invoke(
        app, ["audio", "macro", "run", "da-linha", str(tmp_path / "in"), "--out", str(tmp_path / "out")]
    )
    assert run.exit_code == 0, run.output
    assert "2 de 2 arquivo(s) pronto(s)" in run.output.replace("\n", " ") or "2 de 2 arquivo" in run.output
    assert sorted(p.name for p in (tmp_path / "out").glob("*.mp3")) == ["x.mp3", "y.mp3"]
    status = runner.invoke(app, ["audio", "macro", "status", str(tmp_path / "out")])
    assert status.exit_code == 0 and "x.mp3" in status.output
    no_format = runner.invoke(
        app, ["audio", "macro", "run", "clean_narration", str(tmp_path / "in"), "--out", str(tmp_path / "o2")]
    )
    assert no_format.exit_code == 1 and "formato" in no_format.output
    removed = runner.invoke(app, ["audio", "macro", "remove", "da-linha"])
    assert (
        removed.exit_code == 0
        and runner.invoke(app, ["audio", "macro", "remove", "clean_narration"]).exit_code == 1
    )


def test_the_cli_run_fails_with_exit_code_one_when_a_file_fails(tmp_path, monkeypatch):
    renderer = FakeRenderer(fail_on="y.wav")
    monkeypatch.setattr(macro_run, "PipelineFileRenderer", lambda *args, **kwargs: renderer)
    make_files(tmp_path / "in", ["x.wav", "y.wav"])
    run = runner.invoke(
        app, ["audio", "macro", "run", "mp3_standard", str(tmp_path / "in"), "--out", str(tmp_path / "out")]
    )
    assert run.exit_code == 1 and "y.wav" in run.output
    again = FakeRenderer()
    monkeypatch.setattr(macro_run, "PipelineFileRenderer", lambda *args, **kwargs: again)
    resumed = runner.invoke(
        app,
        [
            "audio",
            "macro",
            "run",
            "mp3_standard",
            str(tmp_path / "in"),
            "--out",
            str(tmp_path / "out"),
            "--resume",
        ],
    )
    assert resumed.exit_code == 0 and again.calls == ["y.wav"]


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


def test_the_ui_routes_list_save_the_chain_of_an_item_and_remove(client):
    catalog = client.get("/api/audio-effects").json()
    assert BUILTIN_MACROS <= {p["id"] for p in catalog["presets"]}
    body = {
        "spec": project_with_chain(
            {"type": "highpass", "frequency_hz": 85, "start": 1.0}, brand="acme"
        ).model_dump(mode="json"),
        "target": "audio.voiceover.0",
        "label": "Pela tela",
        "scope": "brand",
        "summary": "da interface",
        "output": {"preset": "audio/flac"},
    }
    saved = client.post("/api/projects/macro-teste/audio-macros", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["scope"] == "brand:acme" and saved.json()["effects"][0]["frequency_hz"] == 85
    assert "start" not in saved.json()["effects"][0]
    with_brand = client.get("/api/audio-effects", params={"brand": "acme"}).json()["presets"]
    assert "pela-tela" in {p["id"] for p in with_brand}
    assert "pela-tela" not in {p["id"] for p in client.get("/api/audio-effects").json()["presets"]}
    assert [
        p["id"] for p in client.get("/api/audio-effects/presets", params={"brand": "acme"}).json()["presets"]
    ] == ["pela-tela"]
    wrong = client.post(
        "/api/projects/macro-teste/audio-macros", json={**body, "target": "audio.voiceover.1"}
    )
    assert wrong.status_code == 422 and "não tem efeitos" in wrong.json()["detail"]
    plain = client.post(
        "/api/audio-effects/presets",
        json={"label": "Solta", "effects": [{"type": "notch"}], "output": {"preset": "mp3"}},
    )
    assert plain.status_code == 200 and plain.json()["output"] == {"preset": "audio/mp3"}
    assert client.delete("/api/audio-effects/presets/pela-tela", params={"brand": "acme"}).status_code == 200
    assert client.delete("/api/audio-effects/presets/pela-tela", params={"brand": "acme"}).status_code == 404
    assert client.delete("/api/audio-effects/presets/clean_narration").status_code == 404


def test_an_old_project_and_its_hash_are_unaffected_by_macros():
    """Macro é dado de quem usa o editor: nada dela entra na spec, então o hash de um projeto antigo não muda."""
    project = project_with_chain({"type": "highpass", "frequency_hz": 85})
    before = project.to_bytes()
    save_chain_as_macro(project, "audio.voiceover.0", "Qualquer")
    apply_effect_op(project, {"action": "preset", "target": "audio.voiceover.1", "preset": "mp3_standard"})
    assert project.to_bytes() == before
    assert b"macro" not in before.replace(b"macro-teste", b"")  # a spec não tem campo de macro


def test_the_data_folder_is_the_only_place_the_suite_wrote_macros(tmp_path):
    save_user_preset("Só aqui", [{"type": "notch"}])
    assert (config.MACROS_DIR / "so-aqui.json").is_file()
    assert os.fspath(config.MACROS_DIR).startswith(os.fspath(config.DATA_DIR))

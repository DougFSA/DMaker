"""O efeito Plugin no pipeline, sem ffmpeg nem plugin de verdade: o comando de cada estágio (o ffmpeg que hospeda o formato, a pasta
de trabalho e o ambiente), o plugin que não pode rodar sendo pulado com aviso, a chave de cache (a de sempre sem plugin) e o aviso
do `validate_project`."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.audio_effects import chain_signature, parse_effect
from dmaker.domain.plugins import PluginControl, PluginInfo, PluginPorts
from dmaker.domain.spec import Project
from dmaker.media import ffmpeg
from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner, SubprocessRunner
from dmaker.pipeline.audio_effects import EFFECTS_VERSION, AudioItem, EffectProcessor, noise_profile_parts
from dmaker.pipeline.cache_key import cache_key
from dmaker.pipeline.plugin_lint import plugin_references, plugin_warnings
from dmaker.pipeline.plugins import PluginService, PluginUnavailable, ResolvedPlugin

LV2_FFMPEG = Path("lv2-ffmpeg.exe")
LADSPA_FFMPEG = Path("principal-ffmpeg.exe")


class FakeCatalog:
    """O serviço de plugins sem varredura: o que está na lista resolve, o resto some."""

    def __init__(self, tmp_path: Path, enabled: bool = True) -> None:
        self.lv2_binary = tmp_path / "eco.lv2" / "eco.dll"
        self.ladspa_binary = tmp_path / "ladspa" / "eco.dll"
        for binary in (self.lv2_binary, self.ladspa_binary):
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(b"binario")
        controls = (PluginControl("mix", "Mistura", 0.5, 0.0, 1.0),)
        self.plugins = {
            ("lv2", "urn:t:eco"): PluginInfo(
                "lv2",
                "urn:t:eco",
                "Eco",
                str(self.lv2_binary.parent),
                str(self.lv2_binary),
                controls,
                PluginPorts(1, 1),
            ),
            ("ladspa", "eco.dll#eco"): PluginInfo(
                "ladspa",
                "eco.dll#eco",
                "Eco LADSPA",
                str(self.ladspa_binary),
                str(self.ladspa_binary),
                (PluginControl("c0", "Mistura", 0.5, 0.0, 1.0),),  # no LADSPA o nome é a posição
            ),
        }
        self.enabled = enabled
        self.asked: list[tuple[str, str]] = []

    def resolve(self, format_name: str, ref: str) -> ResolvedPlugin:
        self.asked.append((format_name, ref))
        info = self.plugins.get((format_name, ref))
        if info is None:
            raise PluginUnavailable(
                f"o plugin {ref!r} ({format_name.upper()}) não está instalado nesta máquina"
            )
        if not self.enabled:
            raise PluginUnavailable(f"o plugin {info.name!r} está desabilitado")
        if format_name == "lv2":
            return ResolvedPlugin(info, LV2_FFMPEG, None, {"LV2_PATH": str(Path(info.path).parent)})
        return ResolvedPlugin(info, LADSPA_FFMPEG, Path(info.path).parent, {})


def effects(*items: dict):
    return tuple(parse_effect(item) for item in items)


def processor(tmp_path, catalog, warnings=None):
    commands: list[FFmpegCommand] = []
    runner = RecordingRunner(on_run=commands.append)
    return (
        EffectProcessor(
            runner,
            tmp_path / "fx",
            plugins=catalog,
            on_warning=(warnings.append if warnings is not None else None),
        ),
        runner,
        commands,
    )


LV2 = {"type": "plugin", "format": "lv2", "plugin": "urn:t:eco", "params": {"mix": 0.3}}
LADSPA = {"type": "plugin", "format": "ladspa", "plugin": "eco.dll#eco", "params": {"c0": 0.3}}


def test_each_plugin_runs_in_its_own_command_with_the_ffmpeg_folder_and_environment_of_its_format(tmp_path):
    catalog = FakeCatalog(tmp_path)
    runner_processor, runner, commands = processor(tmp_path, catalog)
    chain = effects({"type": "amplify", "gain_db": 2}, LV2, {"type": "amplify", "gain_db": 1}, LADSPA)
    runner_processor.process(AudioItem(tmp_path / "voz.wav", 2.0, chain))
    assert len(commands) == 4  # filtro, plugin LV2, filtro, plugin LADSPA
    assert [c.binary for c in commands] == [None, LV2_FFMPEG, None, LADSPA_FFMPEG]
    assert commands[1].env == {"LV2_PATH": str(tmp_path)} and commands[1].cwd is None
    assert commands[3].env is None and commands[3].cwd == tmp_path / "ladspa"
    graph = commands[1].args[commands[1].args.index("-filter_complex") + 1]
    assert (
        "channelsplit=channel_layout=stereo" in graph
        and graph.count("lv2=p='urn\\:t\\:eco':c='mix=0.3'") == 2
    )
    assert (
        "ladspa=f='./eco.dll':p='eco':c='c0=0.3'"
        in commands[3].args[commands[3].args.index("-filter_complex") + 1]
    )
    assert runner.commands[1][0] == str(LV2_FFMPEG) and runner.commands[0][0] != str(LV2_FFMPEG)
    assert commands[3].args[-1].endswith(".wav")  # o último estágio grava o arquivo final do cache


def test_a_plugin_first_in_the_chain_reads_the_item_and_one_last_writes_the_final_file(tmp_path):
    catalog = FakeCatalog(tmp_path)
    runner_processor, _, commands = processor(tmp_path, catalog)
    runner_processor.process(AudioItem(tmp_path / "voz.wav", 2.0, effects(LV2)))
    assert len(commands) == 1 and str(tmp_path / "voz.wav") in commands[0].args
    assert commands[0].args[-1].endswith(".wav") and "pcm_f32le" in commands[0].args


def test_a_plugin_that_cannot_run_is_skipped_with_a_warning_and_the_rest_of_the_chain_runs(tmp_path):
    catalog = FakeCatalog(tmp_path)
    warnings: list[str] = []
    runner_processor, _, commands = processor(tmp_path, catalog, warnings)
    missing = {"type": "plugin", "format": "lv2", "plugin": "urn:acme:ausente"}
    done = runner_processor.process(
        AudioItem(tmp_path / "voz.wav", 2.0, effects({"type": "amplify", "gain_db": 2}, missing))
    )
    assert done is not None and len(commands) == 1 and commands[0].binary is None
    assert warnings == [
        "efeito Plugin pulado: o plugin 'urn:acme:ausente' (LV2) não está instalado nesta máquina"
    ]


def test_a_chain_with_only_a_missing_plugin_leaves_the_sound_alone(tmp_path):
    runner_processor, _, commands = processor(tmp_path, FakeCatalog(tmp_path), warnings=[])
    assert (
        runner_processor.process(
            AudioItem(tmp_path / "voz.wav", 2.0, effects(LV2 | {"plugin": "urn:acme:x"}))
        )
        is None
    )
    assert commands == []


def test_a_disabled_plugin_is_skipped_too(tmp_path):
    warnings: list[str] = []
    runner_processor, _, commands = processor(tmp_path, FakeCatalog(tmp_path, enabled=False), warnings)
    assert runner_processor.process(AudioItem(tmp_path / "voz.wav", 2.0, effects(LV2))) is None
    assert commands == [] and "desabilitado" in warnings[0]


def graph_of(command: FFmpegCommand) -> str:
    return command.args[command.args.index("-filter_complex") + 1]


def test_a_value_out_of_range_runs_with_the_nearest_limit_and_an_unknown_control_is_left_out(tmp_path):
    warnings: list[str] = []
    runner_processor, _, commands = processor(tmp_path, FakeCatalog(tmp_path), warnings)
    wrong = LV2 | {"params": {"mix": 3, "eco": 1}}
    runner_processor.process(AudioItem(tmp_path / "voz.wav", 2.0, effects(wrong)))
    graph = graph_of(commands[0])
    assert "c='mix=1'" in graph and "mix=3" not in graph and "eco=" not in graph
    assert warnings == [
        "efeito Plugin: o plugin 'Eco' não tem o controle 'eco' (os dele: mix); o render ignora esse valor",
        "efeito Plugin: Eco: Mistura (mix) vale de 0 a 1; 3 está fora, o render usa 1",
    ]


def test_the_warning_comes_once_even_when_the_key_and_the_process_look_at_the_same_item(tmp_path):
    warnings: list[str] = []
    runner_processor, _, _ = processor(tmp_path, FakeCatalog(tmp_path), warnings)
    item = AudioItem(tmp_path / "voz.wav", 2.0, effects(LV2 | {"params": {"mix": 3}}))
    runner_processor.key(item)
    runner_processor.process(item)
    runner_processor.process(item)
    assert len(warnings) == 1


def test_values_inside_the_range_keep_the_command_and_the_key_and_do_not_warn(tmp_path):
    catalog = FakeCatalog(tmp_path)
    warnings: list[str] = []
    runner_processor, _, commands = processor(tmp_path, catalog, warnings)
    source = tmp_path / "voz.wav"
    source.write_bytes(b"x")
    item = AudioItem(source, 2.0, effects(LV2, LADSPA))
    runner_processor.process(item)
    assert "c='mix=0.3'" in graph_of(commands[0]) and "c='c0=0.3'" in graph_of(commands[1])
    assert warnings == []
    chain = effects(LV2, LADSPA)
    hosts = {0: catalog.resolve("lv2", "urn:t:eco"), 1: catalog.resolve("ladspa", "eco.dll#eco")}
    unfitted = cache_key(
        EFFECTS_VERSION,
        str(source),
        (source.stat().st_mtime_ns, source.stat().st_size),
        0,
        0.0,
        2.0,
        "",
        chain_signature(chain),
        hosts[0].signature(),
        hosts[1].signature(),
    )
    assert runner_processor.key(item) == unfitted


def test_the_key_of_a_spec_out_of_range_is_the_one_of_the_spec_already_limited(tmp_path):
    source = tmp_path / "voz.wav"
    source.write_bytes(b"x")
    outside = AudioItem(source, 2.0, effects(LV2 | {"params": {"mix": 3, "eco": 1}}))
    limited = AudioItem(source, 2.0, effects(LV2 | {"params": {"mix": 1}}))
    catalog = FakeCatalog(tmp_path)
    assert processor(tmp_path, catalog)[0].key(outside) == processor(tmp_path, catalog)[0].key(limited)


def test_the_cache_key_without_a_plugin_is_the_one_the_processor_always_made(tmp_path):
    """Projeto antigo igual: a chave de uma cadeia sem plugin não ganha nenhuma parte nova (nem o serviço de plugins é consultado)."""
    catalog = FakeCatalog(tmp_path)
    source = tmp_path / "voz.wav"
    source.write_bytes(b"x" * 10)
    chain = effects({"type": "amplify", "gain_db": 2}, {"type": "invert"})
    item = AudioItem(source, 2.0, chain)
    runner_processor, _, _ = processor(tmp_path, catalog)
    stat = source.stat()
    expected = cache_key(
        EFFECTS_VERSION,
        str(source),
        (stat.st_mtime_ns, stat.st_size),
        0,
        0.0,
        2.0,
        "",
        chain_signature(chain),
    )
    assert runner_processor.key(item) == expected
    assert catalog.asked == []


def test_the_cache_key_changes_when_the_plugin_file_or_the_ffmpeg_that_runs_it_changes(tmp_path):
    catalog = FakeCatalog(tmp_path)
    source = tmp_path / "voz.wav"
    source.write_bytes(b"x")
    item = AudioItem(source, 2.0, effects(LV2))
    first = processor(tmp_path, catalog)[0].key(item)
    assert first == processor(tmp_path, catalog)[0].key(item)
    catalog.lv2_binary.write_bytes(b"binario atualizado")  # o plugin foi atualizado
    assert processor(tmp_path, catalog)[0].key(item) != first


def test_the_parts_for_the_clip_and_preview_keys_are_empty_without_plugins_and_name_the_missing_one(tmp_path):
    from types import SimpleNamespace

    catalog = FakeCatalog(tmp_path)
    real_processor, _, _ = processor(tmp_path, catalog)
    ctx = SimpleNamespace(audio_fx=real_processor)
    assert noise_profile_parts(ctx, effects({"type": "amplify"})) == []  # type: ignore[arg-type]
    assert catalog.asked == []
    (installed,) = noise_profile_parts(ctx, effects(LV2))  # type: ignore[arg-type]
    assert installed[:2] == ["lv2", "urn:t:eco"]
    assert noise_profile_parts(ctx, effects(LV2 | {"plugin": "urn:acme:x"})) == [
        ["ausente", "lv2", "urn:acme:x"]
    ]  # type: ignore[arg-type]


# ---------- o comando com outro ffmpeg ----------


def test_a_command_with_its_own_binary_runs_that_one_and_adds_to_the_environment(monkeypatch):
    seen: dict = {}

    class Stop(Exception):
        pass

    def fake_popen(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        raise Stop

    monkeypatch.setattr(ffmpeg.subprocess, "Popen", fake_popen)
    command = FFmpegCommand(
        ["-i", "a.wav"], binary=Path("outro.exe"), cwd=Path("pasta"), env={"LV2_PATH": "x"}
    )
    with pytest.raises(Stop):
        SubprocessRunner(quiet=True).run(command)
    assert seen["cmd"][0] == "outro.exe" and seen["kwargs"]["cwd"] == "pasta"
    assert seen["kwargs"]["env"]["LV2_PATH"] == "x" and "PATH" in {k.upper() for k in seen["kwargs"]["env"]}
    with pytest.raises(Stop):
        SubprocessRunner(quiet=True).run(FFmpegCommand(["-i", "a.wav"]))
    assert seen["kwargs"]["env"] is None  # sem env próprio, o ambiente do processo, como sempre


# ---------- o aviso do validate ----------


def project_with(*effect_items):
    return Project.model_validate(
        {
            "name": "p",
            "timeline": [{"type": "clip", "src": "a.mp4", "effects": list(effect_items)}],
            "audio": {"music": {"src": "m.wav", "effects": list(effect_items)}},
        }
    )


def test_a_project_without_plugins_does_not_ask_for_the_plugin_service():
    class Boom:
        def resolve(self, format_name, ref):
            raise AssertionError("não devia consultar")

    assert plugin_references(project_with({"type": "amplify"})) == []
    assert plugin_warnings(project_with({"type": "amplify"}), Boom()) == []


def test_a_missing_plugin_is_warned_by_name_once_and_the_project_stays_valid(tmp_path):
    project = project_with({"type": "plugin", "format": "lv2", "plugin": "urn:acme:ausente"})
    warnings = plugin_warnings(project, FakeCatalog(tmp_path))
    assert len(warnings) == 1  # o mesmo plugin no clipe e na música avisa uma vez
    assert "'urn:acme:ausente'" in warnings[0] and "o render pula esse efeito e segue sem ele" in warnings[0]


def test_a_control_the_plugin_does_not_have_or_out_of_range_is_warned_with_the_plugin_name(tmp_path):
    project = project_with(
        {"type": "plugin", "format": "lv2", "plugin": "urn:t:eco", "params": {"mix": 3, "eco": 1}}
    )
    warnings = plugin_warnings(project, FakeCatalog(tmp_path))
    assert any("Eco" in w and "'eco'" in w for w in warnings) and any(
        "Mistura" in w and "0 a 1" in w for w in warnings
    )


def test_summarize_puts_the_plugin_warning_in_the_validation(tmp_path):
    from dmaker.media.probe import MediaInfo
    from dmaker.pipeline.projects import summarize

    def project(*items):
        return Project.model_validate(
            {
                "name": "p",
                "timeline": [{"type": "clip", "src": str(tmp_path / "a.mp4"), "effects": list(items)}],
            }
        )

    def prober(path):
        return MediaInfo(path, 2.0, 1080, 1920, 30.0, True, True, False)

    (tmp_path / "a.mp4").write_bytes(b"x")
    ausente = {"type": "plugin", "format": "lv2", "plugin": "urn:acme:ausente"}
    assert summarize(project(), prober, plugins=FakeCatalog(tmp_path)).warnings == []
    warnings = summarize(project(ausente), prober, plugins=FakeCatalog(tmp_path)).warnings
    assert any("urn:acme:ausente" in warning for warning in warnings)


def test_the_real_service_resolves_nothing_when_no_plugin_is_installed(tmp_path):
    service = PluginService(
        probe=type("P", (), {"report": lambda self, *a, **k: ""})(),
        roots=lambda: [],
        ffmpeg_for=lambda name: LV2_FFMPEG,
    )
    with pytest.raises(PluginUnavailable, match="não está instalado"):
        service.resolve("lv2", "urn:acme:x")

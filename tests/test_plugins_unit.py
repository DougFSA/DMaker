"""Plugins de efeito de terceiros (LV2 e LADSPA), sem ffmpeg nem plugin de verdade: a identidade e a conferência dos controles, o
texto dos filtros, os leitores do que o ffmpeg e os `.ttl` dizem, a varredura (com uma sondagem falsa), o serviço (habilitar,
resolver) e o efeito na spec e na cadeia."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmaker import config
from dmaker.domain.audio_effects import EFFECT_CLASSES, active_effects, catalog_payload, parse_effect
from dmaker.domain.plugins import (
    PluginControl,
    PluginInfo,
    PluginPorts,
    check_params,
    ladspa_ref,
    plugin_id,
    split_ladspa_ref,
)
from dmaker.domain.spec import Project
from dmaker.filtergraph.audio_effects import EffectRequest, build_effect, split_stages
from dmaker.filtergraph.audio_effects.chain import chain_lines
from dmaker.filtergraph.plugins import (
    controls_text,
    escape_option,
    ladspa_filter,
    ladspa_help_graph,
    ladspa_list_graph,
    lv2_filter,
    lv2_help_graph,
    plugin_lines,
)
from dmaker.media import plugin_help
from dmaker.media.plugin_scan import (
    NEEDS_LADSPA_HOST,
    NEEDS_LV2_HOST,
    PluginRoot,
    default_roots,
    find_ladspa_libraries,
    find_lv2_bundles,
    scan_plugins,
)
from dmaker.pipeline.plugins import PluginService, PluginUnavailable

LV2_HELP = """\
[Parsed_lv2_0 @ 0000020342440440] The 'urn:dmaker:test:echo' plugin has the following input controls:
[Parsed_lv2_0 @ 0000020342440440] delay_ms\t\t<float> (from 1.000000 to 1000.000000) (default 250.000000)\t\tAtraso
[Parsed_lv2_0 @ 0000020342440440] feedback\t\t<float> (from 0.000000 to 0.950000) (default 0.400000)\t\tRealimentacao
[Parsed_lv2_0 @ 0000020342440440] mix\t\t<float> (from 0.000000 to 1.000000) (default 0.500000)\t\tMistura
[Parsed_lv2_0 @ 0000020342440440] Failed to configure output pad on Parsed_lv2_0
"""

LV2_FAILURE = """\
non-directory `C:\\plugins\\Hall.vst3` within path entry
error: failed to open file C:/plugins/Hall.vst3/manifest.ttl (No such file or directory)
lilv_world_load_bundle(): error: Error reading <file:///C:/plugins/Hall.vst3/manifest.ttl>
Options feature missing, cannot continue!
[Parsed_lv2_0 @ 000001e226800840] Failed to instantiate <urn:dragonfly:plate>
"""

LADSPA_HELP = """\
[Parsed_ladspa_0 @ 00000258] The 'dm_echo' plugin has the following input controls:
[Parsed_ladspa_0 @ 00000258] c0: Atraso (ms) [<float>, min: 1.000000, max: 1000.000000 (default 500.500000)]
[Parsed_ladspa_0 @ 00000258] c1: Passos [<int>, min: 1.000000, max: 8.000000 (default 4.000000)]
[Parsed_ladspa_0 @ 00000258] c2: Ligado [<toggled>, min: 0.000000, max: 1.000000 (default 1.000000)]
[Parsed_ladspa_0 @ 00000258] c3: Ganho [<float>, logarithmic scale]
"""

LADSPA_LIBRARY = """\
[Parsed_ladspa_0 @ 00000195] The './dm_echo.dll' library contains the following plugins:
[Parsed_ladspa_0 @ 00000195] I = Input Channels
[Parsed_ladspa_0 @ 00000195] O = Output Channels
[Parsed_ladspa_0 @ 00000195] I:O Plugin                    Description
[Parsed_ladspa_0 @ 00000195]
[Parsed_ladspa_0 @ 00000195] 1:1 dm_echo                   DMaker Eco de teste
[Parsed_ladspa_0 @ 00000195] 0:1 dm_gerador                Gerador de teste
"""

MANIFEST = """\
@prefix lv2:  <http://lv2plug.in/ns/lv2core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ui:   <http://lv2plug.in/ns/extensions/ui#> .

<urn:dmaker:test:echo>
    a lv2:Plugin ;
    lv2:binary <dm_echo.dll> ;
    rdfs:seeAlso <dm_echo.ttl> .

<urn:dmaker:test:echo#UI>
    a ui:WindowsUI ;
    ui:binary <dm_echo_ui.dll> ;
    rdfs:seeAlso <dm_echo_ui.ttl> .
"""

PLUGIN_TTL = """\
@prefix doap: <http://usefulinc.com/ns/doap#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix lv2:  <http://lv2plug.in/ns/lv2core#> .
@prefix opts: <http://lv2plug.in/ns/ext/options#> .

<urn:dmaker:test:echo>
    a lv2:DelayPlugin, lv2:Plugin ;
    doap:name "DMaker Eco" ;
    doap:maker [ foaf:name "DMaker" ] ;
    lv2:requiredFeature opts:options ,
                        <http://lv2plug.in/ns/ext/urid#map> ;
    lv2:port [
        a lv2:InputPort, lv2:ControlPort ;
        lv2:index 0 ;
        lv2:symbol "delay_ms" ;
    ] , [
        a lv2:InputPort, lv2:AudioPort ;
        lv2:index 1 ;
        lv2:symbol "in" ;
    ] , [
        a lv2:OutputPort, lv2:AudioPort ;
        lv2:index 2 ;
        lv2:symbol "out" ;
    ] .
"""


# ---------- identidade e conferência ----------


def test_the_id_is_short_stable_and_tells_the_format():
    assert plugin_id("lv2", "urn:a:b") == plugin_id("lv2", "urn:a:b")
    assert plugin_id("lv2", "urn:a:b").startswith("lv2-") and len(plugin_id("lv2", "urn:a:b")) == 14
    assert plugin_id("lv2", "urn:a:b") != plugin_id("ladspa", "urn:a:b")


def test_a_ladspa_reference_joins_the_library_and_the_label_and_splits_back():
    assert ladspa_ref("cmt.dll", "delay_5s") == "cmt.dll#delay_5s"
    assert split_ladspa_ref("cmt.dll#delay_5s") == ("cmt.dll", "delay_5s")
    for bad in ("cmt.dll", "#x", "cmt.dll#"):
        with pytest.raises(ValueError, match="separados por"):
            split_ladspa_ref(bad)


def info(**changes) -> PluginInfo:
    base = PluginInfo(
        "lv2",
        "urn:dmaker:test:echo",
        "Eco",
        "C:/p/echo.lv2",
        "C:/p/echo.lv2/echo.dll",
        controls=(
            PluginControl("delay_ms", "Atraso", 250.0, 1.0, 1000.0),
            PluginControl("mix", "Mistura", 0.5, 0.0, None),
        ),
    )
    return PluginInfo(**{**base.__dict__, **changes})


def test_the_parameters_are_checked_against_the_range_the_plugin_declares():
    plugin = info()
    assert check_params(plugin, {"delay_ms": 300, "mix": 2}) == []  # sem teto declarado, qualquer valor serve
    unknown = check_params(plugin, {"eco": 1})
    assert len(unknown) == 1 and "não tem o controle 'eco'" in unknown[0] and "delay_ms, mix" in unknown[0]
    outside = check_params(plugin, {"delay_ms": 5000})
    assert len(outside) == 1 and "1 a 1000" in outside[0] and "5000" in outside[0]


def test_the_info_round_trips_through_its_dict_with_the_id_and_the_enabled_state():
    plugin = info(enabled=False, ports=PluginPorts(1, 2), problem="x", usable=False)
    data = plugin.to_dict()
    assert data["id"] == plugin.id and data["enabled"] is False
    assert PluginInfo.from_dict(json.loads(json.dumps(data))) == plugin


# ---------- o texto dos filtros ----------


def test_an_option_value_is_quoted_with_the_backslash_and_the_colon_escaped():
    assert escape_option("urn:a:b") == "'urn\\:a\\:b'"
    assert escape_option(r"C:\x") == "'C\\:\\\\x'"
    with pytest.raises(ValueError, match="aspas simples"):
        escape_option("it's")


def test_the_controls_are_written_sorted_and_with_nine_significant_digits_and_empty_means_the_default():
    assert controls_text({"mix": 0.5, "delay_ms": 300}) == "delay_ms=300|mix=0.5"
    assert controls_text({"x": 1 / 3}) == "x=0.333333333"
    assert controls_text({}) == ""


def test_the_lv2_filter_names_the_uri_and_only_carries_the_controls_that_were_given():
    assert lv2_filter("urn:a:b", {}) == "lv2=p='urn\\:a\\:b'"
    assert lv2_filter("https://x.org/p", {"gain": 2}) == "lv2=p='https\\://x.org/p':c='gain=2'"


def test_the_ladspa_filter_points_at_the_library_in_the_working_folder():
    # o ffmpeg só carrega por caminho se começa com `.` ou `/`: a biblioteca é citada como ./nome e a pasta vira o cwd
    assert ladspa_filter("cmt.dll#delay_5s", {"c0": 1.5}) == "ladspa=f='./cmt.dll':p='delay_5s':c='c0=1.5'"
    assert ladspa_filter("cmt.dll#delay_5s", {}) == "ladspa=f='./cmt.dll':p='delay_5s'"


def test_the_probe_graphs_ask_the_filter_for_the_controls_or_the_plugins_of_a_library():
    assert lv2_help_graph("urn:a:b") == "lv2=p='urn\\:a\\:b':c=help"
    assert ladspa_list_graph("cmt.dll") == "ladspa=f='./cmt.dll'"
    assert ladspa_help_graph("cmt.dll", "delay") == "ladspa=f='./cmt.dll':p='delay':c=help"


@pytest.mark.parametrize(
    ("ports", "expected"),
    [
        (PluginPorts(2, 2), ["[in]lv2=p='urn\\:a':c='x=1',pan=stereo|c0=c0|c1=c1[out]"]),
        (PluginPorts(2, 1), ["[in]lv2=p='urn\\:a':c='x=1',pan=stereo|c0=c0|c1=c0[out]"]),
        (
            PluginPorts(1, 2),
            ["[in]pan=mono|c0=0.5*c0+0.5*c1,lv2=p='urn\\:a':c='x=1',pan=stereo|c0=c0|c1=c1[out]"],
        ),
    ],
)
def test_a_lv2_plugin_with_two_inputs_or_a_mono_downmix_is_one_line(ports, expected):
    assert plugin_lines("lv2", "urn:a", {"x": 1}, ports, "[in]", "[out]", "fx0") == expected


def test_a_mono_lv2_plugin_runs_once_per_channel_and_the_channels_are_joined_back():
    lines = plugin_lines("lv2", "urn:a", {}, PluginPorts(1, 1), "[in]", "[out]", "fx0")
    assert lines[0] == "[in]channelsplit=channel_layout=stereo[fx0_l][fx0_r]"
    assert lines[1] == "[fx0_l]lv2=p='urn\\:a'[fx0_lo]" and lines[2] == "[fx0_r]lv2=p='urn\\:a'[fx0_ro]"
    assert lines[3] == "[fx0_lo][fx0_ro]amerge=inputs=2,pan=stereo|c0=c0|c1=c1[out]"


def test_a_ladspa_plugin_is_one_line_because_the_filter_makes_one_instance_per_channel():
    lines = plugin_lines("ladspa", "a.dll#x", {"c0": 2}, PluginPorts(1, 1), "[in]", "[out]", "fx0")
    assert lines == ["[in]ladspa=f='./a.dll':p='x':c='c0=2',aformat=channel_layouts=stereo[out]"]


# ---------- ler o que o ffmpeg e os .ttl dizem ----------


def test_the_lv2_controls_come_from_the_help_report_with_range_default_and_label():
    controls = plugin_help.parse_lv2_controls(LV2_HELP)
    assert [(c.name, c.label, c.default, c.minimum, c.maximum, c.kind) for c in controls] == [
        ("delay_ms", "Atraso", 250.0, 1.0, 1000.0, "number"),
        ("feedback", "Realimentacao", 0.4, 0.0, 0.95, "number"),
        ("mix", "Mistura", 0.5, 0.0, 1.0, "number"),
    ]


def test_the_ladspa_controls_are_named_by_position_and_keep_the_type_and_a_missing_range():
    controls = plugin_help.parse_ladspa_controls(LADSPA_HELP)
    assert [(c.name, c.label, c.kind) for c in controls] == [
        ("c0", "Atraso (ms)", "number"),
        ("c1", "Passos", "integer"),
        ("c2", "Ligado", "boolean"),
        ("c3", "Ganho", "number"),
    ]
    assert (controls[0].default, controls[0].minimum, controls[0].maximum) == (500.5, 1.0, 1000.0)
    assert (controls[3].default, controls[3].minimum, controls[3].maximum) == (0.0, None, None)


def test_the_plugins_of_a_ladspa_library_come_with_their_audio_ports():
    entries = plugin_help.parse_ladspa_library(LADSPA_LIBRARY)
    assert [(e.label, e.name, e.inputs, e.outputs) for e in entries] == [
        ("dm_echo", "DMaker Eco de teste", 1, 1),
        ("dm_gerador", "Gerador de teste", 0, 1),
    ]


def test_the_failure_line_keeps_the_plugin_complaint_and_drops_the_loader_noise():
    assert plugin_help.failure_line(LV2_FAILURE) == (
        "Options feature missing, cannot continue! | Failed to instantiate <urn:dragonfly:plate>"
    )
    assert plugin_help.failure_line(LV2_HELP.replace("Failed to configure", "Configured")) == ""


def test_the_manifest_lists_the_plugins_and_skips_the_user_interface():
    (plugin,) = plugin_help.manifest_plugins(MANIFEST)
    assert (plugin.uri, plugin.binary, plugin.description) == (
        "urn:dmaker:test:echo",
        "dm_echo.dll",
        "dm_echo.ttl",
    )


def test_the_description_counts_the_audio_ports_and_names_what_the_plugin_asks_of_the_host():
    description = plugin_help.describe_lv2(PLUGIN_TTL, "urn:dmaker:test:echo")
    assert (description.name, description.audio_inputs, description.audio_outputs) == ("DMaker Eco", 1, 1)
    assert description.required_features == (
        "http://lv2plug.in/ns/ext/options#options",
        "http://lv2plug.in/ns/ext/urid#map",
    )
    assert description.unsupported_features == ("http://lv2plug.in/ns/ext/options#options",)


# ---------- a varredura ----------


class FakeProbe:
    """A sondagem sem ffmpeg: devolve o relatório guardado para o gráfico pedido."""

    def __init__(self, reports: dict[str, str]) -> None:
        self.reports = reports
        self.calls: list[tuple[str, Path | None, dict | None]] = []

    def report(self, ffmpeg, graph, cwd=None, env=None):
        self.calls.append((graph, cwd, dict(env) if env else None))
        return self.reports.get(graph, "")


def make_lv2_bundle(
    root: Path, name: str = "echo.lv2", manifest: str = MANIFEST, ttl: str = PLUGIN_TTL
) -> Path:
    bundle = root / name
    bundle.mkdir(parents=True)
    (bundle / "manifest.ttl").write_text(manifest, encoding="utf-8")
    (bundle / "dm_echo.ttl").write_text(ttl, encoding="utf-8")
    (bundle / "dm_echo.dll").write_bytes(b"x")
    return bundle


def test_the_bundles_and_libraries_are_found_in_the_folders_of_their_format(tmp_path):
    make_lv2_bundle(tmp_path / "lv2")
    (tmp_path / "lv2" / "sem_manifest.lv2").mkdir()
    (tmp_path / "ladspa").mkdir()
    (tmp_path / "ladspa" / "a.dll").write_bytes(b"x")
    (tmp_path / "ladspa" / "leia-me.txt").write_text("x")
    roots = [PluginRoot("lv2", tmp_path / "lv2"), PluginRoot("ladspa", tmp_path / "ladspa")]
    assert [b.name for b in find_lv2_bundles(roots)] == ["echo.lv2"]
    assert [lib.name for lib in find_ladspa_libraries(roots)] == ["a.dll"]


def test_the_dmaker_folder_accepts_a_bundle_one_level_down(tmp_path):
    make_lv2_bundle(tmp_path / "pacote-do-plugin")
    assert [b.name for b in find_lv2_bundles([PluginRoot("lv2", tmp_path)])] == ["echo.lv2"]


def test_the_default_roots_start_with_the_dmaker_folder_and_follow_the_environment():
    environ = {
        "LV2_PATH": f"C:/a{__import__('os').pathsep}C:/b",
        "LADSPA_PATH": "C:/l",
        "APPDATA": "C:/Roaming",
    }
    roots = default_roots(environ, "win32")
    assert roots[0] == PluginRoot("lv2", config.PLUGINS_DIR)
    paths = {(root.format, Path(root.path).as_posix()) for root in roots}
    assert {("lv2", "C:/a"), ("lv2", "C:/b"), ("ladspa", "C:/l"), ("lv2", "C:/Roaming/LV2")} <= paths
    assert not any(
        root.path == Path("/usr/lib/lv2") for root in roots
    )  # as pastas do Linux não entram no Windows


def test_a_usable_lv2_plugin_comes_with_its_controls_ports_and_name(tmp_path):
    bundle = make_lv2_bundle(tmp_path)
    probe = FakeProbe({lv2_help_graph("urn:dmaker:test:echo"): LV2_HELP})
    # o plugin do teste pede `options`, mas o ffmpeg o carregou: vale o que o ffmpeg diz, não o que o .ttl declara
    result = scan_plugins([PluginRoot("lv2", tmp_path)], probe, lambda name: Path("ffmpeg-lv2"))
    (plugin,) = result.plugins
    assert (plugin.format, plugin.ref, plugin.name, plugin.usable) == (
        "lv2",
        "urn:dmaker:test:echo",
        "DMaker Eco",
        True,
    )
    assert plugin.ports == PluginPorts(1, 1) and [c.name for c in plugin.controls] == [
        "delay_ms",
        "feedback",
        "mix",
    ]
    assert plugin.path == str(bundle) and plugin.binary.endswith("dm_echo.dll")
    assert probe.calls[0][2] == {"LV2_PATH": str(tmp_path)}  # o ffmpeg procura só no pacote


def test_an_lv2_plugin_the_ffmpeg_cannot_host_says_why_and_names_the_feature_it_needs(tmp_path):
    make_lv2_bundle(tmp_path)
    probe = FakeProbe({lv2_help_graph("urn:dmaker:test:echo"): LV2_FAILURE})
    (plugin,) = scan_plugins([PluginRoot("lv2", tmp_path)], probe, lambda name: Path("ffmpeg-lv2")).plugins
    assert not plugin.usable and plugin.controls == ()
    assert "Options feature missing" in plugin.problem and "o plugin exige options" in plugin.problem


def test_without_the_lv2_ffmpeg_the_plugin_is_listed_but_not_usable_and_the_fix_is_in_the_note(tmp_path):
    make_lv2_bundle(tmp_path)
    result = scan_plugins([PluginRoot("lv2", tmp_path)], FakeProbe({}), lambda name: None)
    assert result.plugins[0].problem == NEEDS_LV2_HOST and not result.plugins[0].usable
    assert result.notes and "dmaker setup --plugins" in result.notes[0]


def test_a_ladspa_library_gives_one_plugin_per_label_and_a_generator_is_not_usable(tmp_path):
    (tmp_path / "dm_echo.dll").write_bytes(b"x")
    probe = FakeProbe(
        {
            ladspa_list_graph("dm_echo.dll"): LADSPA_LIBRARY,
            ladspa_help_graph("dm_echo.dll", "dm_echo"): LADSPA_HELP,
        }
    )
    result = scan_plugins([PluginRoot("ladspa", tmp_path)], probe, lambda name: Path("ffmpeg"))
    echo, generator = result.plugins
    assert (
        echo.ref == "dm_echo.dll#dm_echo"
        and echo.usable
        and [c.name for c in echo.controls][:2] == ["c0", "c1"]
    )
    assert not generator.usable and "sem entrada" in generator.problem.replace(
        "não tem entrada de áudio", "sem entrada"
    )
    assert all(
        cwd == tmp_path for _, cwd, _ in probe.calls
    )  # a biblioteca é aberta com a pasta dela como pasta de trabalho


def test_without_a_ladspa_ffmpeg_the_libraries_are_left_out_with_a_note(tmp_path):
    (tmp_path / "a.dll").write_bytes(b"x")
    result = scan_plugins([PluginRoot("ladspa", tmp_path)], FakeProbe({}), lambda name: None)
    assert result.plugins == [] and NEEDS_LADSPA_HOST in result.notes[0]


def test_the_same_plugin_in_two_folders_counts_once_and_the_first_folder_wins(tmp_path):
    make_lv2_bundle(tmp_path / "primeira")
    make_lv2_bundle(tmp_path / "segunda")
    roots = [PluginRoot("lv2", tmp_path / "primeira"), PluginRoot("lv2", tmp_path / "segunda")]
    probe = FakeProbe({lv2_help_graph("urn:dmaker:test:echo"): LV2_HELP})
    (plugin,) = scan_plugins(roots, probe, lambda name: Path("ffmpeg")).plugins
    assert "primeira" in plugin.path


# ---------- o serviço ----------


def service_for(tmp_path, ffmpeg=Path("ffmpeg"), reports=None):
    make_lv2_bundle(tmp_path / "lv2")
    probe = FakeProbe(reports if reports is not None else {lv2_help_graph("urn:dmaker:test:echo"): LV2_HELP})
    return PluginService(probe, lambda: [PluginRoot("lv2", tmp_path / "lv2")], lambda name: ffmpeg), probe


def test_the_scan_is_kept_in_the_cache_folder_and_read_back_without_asking_the_ffmpeg_again(tmp_path):
    service, probe = service_for(tmp_path)
    service.scan()
    asked = len(probe.calls)
    assert (config.PLUGIN_SCAN_DIR / "scan.json").exists()
    assert [p.ref for p in service.plugins()] == ["urn:dmaker:test:echo"] and len(probe.calls) == asked


def test_disabling_a_plugin_is_kept_in_plugins_json_and_resolving_it_then_says_so(tmp_path):
    service, _ = service_for(tmp_path)
    plugin = service.plugins()[0]
    service.set_enabled(plugin.id, False)
    assert json.loads(config.PLUGINS_FILE.read_text(encoding="utf-8")) == {
        "disabled": ["lv2:urn:dmaker:test:echo"]
    }
    assert service.find(plugin.id).enabled is False
    with pytest.raises(PluginUnavailable, match="desabilitado"):
        service.resolve("lv2", plugin.ref)
    service.set_enabled(plugin.ref, True)  # pela referência também
    assert json.loads(config.PLUGINS_FILE.read_text(encoding="utf-8")) == {"disabled": []}
    assert service.resolve("lv2", plugin.ref).info.name == "DMaker Eco"


def test_resolving_gives_the_ffmpeg_the_folder_and_the_environment_the_format_needs(tmp_path):
    service, _ = service_for(tmp_path, ffmpeg=Path("C:/ff/ffmpeg.exe"))
    resolved = service.resolve("lv2", "urn:dmaker:test:echo")
    assert resolved.ffmpeg == Path("C:/ff/ffmpeg.exe") and resolved.cwd is None
    assert resolved.env == {"LV2_PATH": str(tmp_path / "lv2")}
    assert resolved.ports == PluginPorts(1, 1)
    assert resolved.signature()[:2] == ["lv2", "urn:dmaker:test:echo"]


def test_resolving_an_unknown_plugin_scans_once_more_and_then_gives_up_with_the_reference(tmp_path):
    service, probe = service_for(tmp_path)
    service.scan()
    asked = len(probe.calls)
    with pytest.raises(PluginUnavailable, match="urn:acme:nada.*não está instalado"):
        service.resolve("lv2", "urn:acme:nada")
    assert len(probe.calls) == asked  # a varredura deste serviço já tinha rodado: não repete a cada pergunta


def test_resolving_without_the_ffmpeg_or_with_an_unusable_plugin_says_what_to_do(tmp_path):
    service, _ = service_for(tmp_path, ffmpeg=None)  # type: ignore[arg-type]
    with pytest.raises(PluginUnavailable, match="dmaker setup --plugins"):
        service.resolve("lv2", "urn:dmaker:test:echo")
    broken, _ = service_for(tmp_path / "outro", reports={lv2_help_graph("urn:dmaker:test:echo"): LV2_FAILURE})
    broken.scan()  # a varredura guardada pelo serviço de cima não vale para este
    with pytest.raises(PluginUnavailable, match="não pode ser usado: Options feature missing"):
        broken.resolve("lv2", "urn:dmaker:test:echo")


def test_the_catalog_carries_the_plugins_the_ffmpeg_of_each_format_and_where_to_put_plugins(tmp_path):
    service, _ = service_for(tmp_path)
    payload = service.catalog()
    assert [p["ref"] for p in payload["plugins"]] == ["urn:dmaker:test:echo"]
    assert payload["hosts"] == {"lv2": "ffmpeg", "ladspa": "ffmpeg"}
    assert payload["install_to"] == str(config.PLUGINS_DIR)
    assert service.catalog(payload["plugins"][0]["id"])["plugins"][0]["name"] == "DMaker Eco"
    with pytest.raises(PluginUnavailable, match="não encontrado"):
        service.catalog("nada")
    json.dumps(payload)  # a rota da API e o MCP devolvem isto


# ---------- o efeito na spec e na cadeia ----------


def plugin_effect(**changes):
    return parse_effect({"type": "plugin", "format": "lv2", "plugin": "urn:dmaker:test:echo", **changes})


def test_the_plugin_effect_is_registered_with_a_builder_and_marked_item_only_and_needs_a_choice():
    cls = EFFECT_CLASSES["plugin"]
    assert cls.separate_stage and cls.item_only() and cls.needs_selection and not cls.sample_stage
    by_type = {effect["type"]: effect for effect in catalog_payload()["effects"]}
    plugin = by_type["plugin"]
    assert (
        plugin["needs_selection"] and plugin["sample_stage"]
    )  # o menu genérico não o oferece e o mestre o recusa
    kinds = {parameter["name"]: parameter["kind"] for parameter in plugin["parameters"]}
    assert kinds == {"format": "plugin_format", "plugin": "plugin", "params": "plugin_params"}


def test_the_effect_needs_a_plugin_a_valid_ladspa_reference_and_clean_control_names():
    with pytest.raises(ValidationError, match="diga qual plugin"):
        parse_effect({"type": "plugin"})
    with pytest.raises(ValidationError, match="arquivo e o rótulo"):
        parse_effect({"type": "plugin", "format": "ladspa", "plugin": "so_o_arquivo.dll"})
    with pytest.raises(ValidationError, match="nome de controle válido"):
        plugin_effect(params={"a b": 1})
    with pytest.raises(ValidationError):
        plugin_effect(params={"a": float("inf")})
    with pytest.raises(ValidationError):
        plugin_effect(format="vst3")


def test_the_order_of_the_controls_does_not_change_the_effect_or_its_cache_signature():
    first = plugin_effect(params={"mix": 0.5, "delay_ms": 300})
    second = plugin_effect(params={"delay_ms": 300, "mix": 0.5})
    assert list(first.params) == ["delay_ms", "mix"] and first.model_dump() == second.model_dump()


def test_the_master_refuses_a_plugin_and_says_it_runs_apart_from_the_mix_graph():
    with pytest.raises(
        ValidationError, match="roda num comando à parte do ffmpeg e não vale na mistura inteira"
    ):
        Project.model_validate(
            {
                "name": "x",
                "timeline": [{"type": "clip", "src": "a.mp4"}],
                "audio": {"master_effects": [{"type": "plugin", "format": "lv2", "plugin": "urn:a"}]},
            }
        )
    ok = Project.model_validate(
        {
            "name": "x",
            "timeline": [
                {
                    "type": "clip",
                    "src": "a.mp4",
                    "effects": [{"type": "plugin", "format": "lv2", "plugin": "urn:a", "params": {"g": 1}}],
                }
            ],
        }
    )
    assert (
        ok.timeline[0].effects[0].host_format() == "lv2"
        and ok.timeline[0].effects[0].host_reference() == "urn:a"
    )


def test_a_project_without_plugins_dumps_the_same_effects_as_before():
    clip = {"type": "clip", "src": "a.mp4", "effects": [{"type": "amplify", "gain_db": 3}]}
    dumped = Project.model_validate({"name": "x", "timeline": [clip]}).model_dump(
        mode="json", exclude_none=True
    )
    assert dumped["timeline"][0]["effects"] == [
        {"type": "amplify", "enabled": True, "gain_db": 3.0, "prevent_clipping": False}
    ]


def test_the_chain_gives_each_plugin_its_own_stage_between_the_filter_stages():
    chain = [
        parse_effect({"type": "amplify", "gain_db": 1}),
        plugin_effect(),
        parse_effect({"type": "amplify", "gain_db": 2}),
        parse_effect({"type": "plugin", "format": "ladspa", "plugin": "a.dll#x"}),
        plugin_effect(enabled=False),
    ]
    stages = split_stages(chain)
    assert [(stage.host, stage.samples, [i for i, _ in stage.effects]) for stage in stages] == [
        (None, False, [0]),
        ("lv2", False, [1]),
        (None, False, [2]),
        ("ladspa", False, [3]),
    ]
    assert [i for i, _ in active_effects(chain)] == [0, 1, 2, 3]


def test_the_builder_adapts_to_the_ports_and_a_plugin_in_an_interval_is_crossfaded_like_any_effect():
    effect = plugin_effect(params={"mix": 0.5}, start=1.0, end=2.0)
    ports = {0: PluginPorts(1, 1)}
    lines = chain_lines("[in]", "[out]", [effect], 3.0, ports=ports)
    text = ";".join(lines)
    assert (
        "channelsplit=channel_layout=stereo" in text and text.count("lv2=p='urn\\:dmaker\\:test\\:echo'") == 2
    )
    assert "amix=inputs=3" in text and "afade=t=in" in text  # a emenda de 10 ms do intervalo
    assert build_effect(EffectRequest(plugin_effect(), "[a]", "[b]", "t", 1.0))[-1].endswith(
        "[b]"
    )  # sem portas: direto

"""A varredura dos plugins instalados: acha os pacotes LV2 e as bibliotecas LADSPA nas pastas padrão do sistema (só leitura) e
na pasta do DMaker, e pergunta ao ffmpeg o que cada um expõe, como o Gerenciador de Plugins do Audacity.

O que é do disco e do ambiente (as pastas, os arquivos) fica em `default_roots`/`find_*`; o que é do ffmpeg entra por
`PluginProbe`, e o ffmpeg de cada formato por `ffmpeg_for`. Assim a varredura se testa com plugins de mentira.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..domain.plugins import PluginInfo, PluginPorts, ladspa_ref
from ..filtergraph.plugins import ladspa_help_graph, ladspa_list_graph, lv2_help_graph
from .plugin_help import (
    describe_lv2,
    failure_line,
    manifest_plugins,
    parse_ladspa_controls,
    parse_ladspa_library,
    parse_lv2_controls,
)
from .plugin_host import PluginProbe

NEEDS_LV2_HOST = "falta o ffmpeg que hospeda o LV2: rode `dmaker setup --plugins`"
NEEDS_LADSPA_HOST = (
    "o ffmpeg principal não tem o filtro ladspa: rode `dmaker setup` para instalar o build completo"
)
LIBRARY_SUFFIXES = (".dll", ".so", ".dylib")


@dataclass(frozen=True)
class PluginRoot:
    """Uma pasta onde se procura plugins de um formato."""

    format: str
    path: Path


@dataclass
class ScanResult:
    """O que a varredura achou e o que ela não conseguiu ler (bibliotecas LADSPA sem o ffmpeg que as lê, por exemplo)."""

    plugins: list[PluginInfo] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _split(value: str | None) -> list[str]:
    return [item for item in (value or "").split(os.pathsep) if item]


def default_roots(environ: Mapping[str, str] | None = None, platform: str | None = None) -> list[PluginRoot]:
    """As pastas da varredura, na ordem de prioridade: a do DMaker, as variáveis `LV2_PATH` e `LADSPA_PATH` e as pastas
    padrão do sistema que o Audacity também lê. Só leitura: o DMaker nunca instala nada nas do sistema."""
    env = os.environ if environ is None else environ
    system = sys.platform if platform is None else platform
    home = Path(env.get("USERPROFILE") or env.get("HOME") or "~").expanduser()
    roots = [
        PluginRoot("lv2", config.PLUGINS_DIR),
        PluginRoot("lv2", config.PLUGINS_DIR / "lv2"),
        PluginRoot("ladspa", config.PLUGINS_DIR / "ladspa"),
    ]
    roots += [PluginRoot("lv2", Path(item)) for item in _split(env.get("LV2_PATH"))]
    roots += [PluginRoot("ladspa", Path(item)) for item in _split(env.get("LADSPA_PATH"))]
    if system.startswith("win"):
        for variable in ("APPDATA", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)"):
            if env.get(variable):
                roots.append(PluginRoot("lv2", Path(env[variable]) / "LV2"))
        if env.get("PROGRAMFILES"):
            roots.append(PluginRoot("ladspa", Path(env["PROGRAMFILES"]) / "Audacity" / "Plug-Ins"))
    elif system == "darwin":
        roots += [
            PluginRoot("lv2", home / "Library/Audio/Plug-Ins/LV2"),
            PluginRoot("lv2", Path("/Library/Audio/Plug-Ins/LV2")),
            PluginRoot("ladspa", home / "Library/Audio/Plug-Ins/LADSPA"),
            PluginRoot("ladspa", Path("/Library/Audio/Plug-Ins/LADSPA")),
        ]
    else:
        roots += [
            PluginRoot("lv2", home / ".lv2"),
            PluginRoot("lv2", Path("/usr/local/lib/lv2")),
            PluginRoot("lv2", Path("/usr/lib/lv2")),
            PluginRoot("ladspa", home / ".ladspa"),
            PluginRoot("ladspa", Path("/usr/local/lib/ladspa")),
            PluginRoot("ladspa", Path("/usr/lib/ladspa")),
        ]
    return roots


def _children(folder: Path) -> list[Path]:
    try:
        return sorted(folder.iterdir())
    except OSError:
        return []


def find_lv2_bundles(roots: Iterable[PluginRoot]) -> list[Path]:
    """Os pacotes LV2 (`*.lv2` com `manifest.ttl`) direto dentro das pastas. A pasta do DMaker aceita também um nível de
    subpasta, para quem descompacta o pacote do plugin lá sem separar os formatos."""
    found: list[Path] = []
    for root in roots:
        if root.format != "lv2":
            continue
        for child in _children(root.path):
            candidates = [child] + (_children(child) if child.is_dir() and child.suffix != ".lv2" else [])
            for candidate in candidates:
                if (
                    candidate.suffix == ".lv2"
                    and (candidate / "manifest.ttl").is_file()
                    and candidate not in found
                ):
                    found.append(candidate)
    return found


def find_ladspa_libraries(roots: Iterable[PluginRoot]) -> list[Path]:
    """As bibliotecas LADSPA (`.dll`, `.so`) das pastas."""
    found: list[Path] = []
    for root in roots:
        if root.format != "ladspa":
            continue
        for child in _children(root.path):
            if child.suffix.lower() in LIBRARY_SUFFIXES and child.is_file() and child not in found:
                found.append(child)
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def scan_lv2(bundle: Path, probe: PluginProbe, ffmpeg: Path | None) -> list[PluginInfo]:
    """Os plugins de um pacote LV2: o `manifest.ttl` diz quais são, o `.ttl` de cada um quantas portas de áudio tem e o que exige
    do hospedeiro, e o ffmpeg lista os controles (e diz se consegue instanciá-lo)."""
    infos = []
    for declared in manifest_plugins(_read(bundle / "manifest.ttl")):
        description = describe_lv2(_read(bundle / declared.description), declared.uri)
        problem = ""
        controls = ()
        if ffmpeg is None:
            problem = NEEDS_LV2_HOST
        else:
            report = probe.report(ffmpeg, lv2_help_graph(declared.uri), env={"LV2_PATH": str(bundle.parent)})
            controls = tuple(parse_lv2_controls(report))
            if not controls:
                problem = failure_line(report)
            if problem and description.unsupported_features:
                missing = ", ".join(
                    feature.rsplit("#", 1)[-1] for feature in description.unsupported_features
                )
                problem += f" (o plugin exige {missing}, que o ffmpeg não oferece ao hospedar LV2)"
        if not problem and description.audio_inputs == 0:
            problem = (
                "o plugin não tem entrada de áudio (é um instrumento ou gerador); o ffmpeg só hospeda efeitos"
            )
        infos.append(
            PluginInfo(
                format="lv2",
                ref=declared.uri,
                name=description.name,
                path=str(bundle),
                binary=str(bundle / declared.binary) if declared.binary else "",
                controls=controls,
                ports=PluginPorts(description.audio_inputs, description.audio_outputs),
                maker=description.maker,
                usable=not problem,
                problem=problem,
            )
        )
    return infos


def scan_ladspa(library: Path, probe: PluginProbe, ffmpeg: Path) -> list[PluginInfo]:
    """Os plugins de uma biblioteca LADSPA: o ffmpeg lista os rótulos (com as portas de áudio) e, para cada um, os controles. A
    biblioteca é citada como `./nome` com a pasta dela como pasta de trabalho (ver `filtergraph.plugins`)."""
    folder = library.parent
    entries = parse_ladspa_library(probe.report(ffmpeg, ladspa_list_graph(library.name), cwd=folder))
    infos = []
    for entry in entries:
        report = probe.report(ffmpeg, ladspa_help_graph(library.name, entry.label), cwd=folder)
        problem = ""
        if entry.inputs == 0:
            problem = "o plugin não tem entrada de áudio (é um gerador); o ffmpeg só hospeda efeitos"
        elif entry.outputs == 0:
            problem = "o plugin não tem saída de áudio"
        infos.append(
            PluginInfo(
                format="ladspa",
                ref=ladspa_ref(library.name, entry.label),
                name=entry.name,
                path=str(library),
                binary=str(library),
                controls=tuple(parse_ladspa_controls(report)),
                ports=PluginPorts(entry.inputs, entry.outputs),
                usable=not problem,
                problem=problem,
            )
        )
    return infos


def scan_plugins(
    roots: Iterable[PluginRoot],
    probe: PluginProbe,
    ffmpeg_for: Callable[[str], Path | None],
) -> ScanResult:
    """A varredura inteira. O mesmo plugin em duas pastas vale uma vez, o da pasta que vem primeiro (a do DMaker)."""
    roots = list(roots)
    result = ScanResult()
    seen: set[tuple[str, str]] = set()

    def keep(infos: list[PluginInfo]) -> None:
        for info in infos:
            if (info.format, info.ref) not in seen:
                seen.add((info.format, info.ref))
                result.plugins.append(info)

    lv2_ffmpeg = ffmpeg_for("lv2")
    for bundle in find_lv2_bundles(roots):
        keep(scan_lv2(bundle, probe, lv2_ffmpeg))
    libraries = find_ladspa_libraries(roots)
    ladspa_ffmpeg = ffmpeg_for("ladspa")
    if ladspa_ffmpeg is None:
        if libraries:
            result.notes.append(f"{len(libraries)} biblioteca(s) LADSPA não foram lidas: {NEEDS_LADSPA_HOST}")
    else:
        for library in libraries:
            keep(scan_ladspa(library, probe, ladspa_ffmpeg))
    if lv2_ffmpeg is None and any(info.format == "lv2" for info in result.plugins):
        result.notes.append(f"plugins LV2 achados, mas não usáveis: {NEEDS_LV2_HOST}")
    return result

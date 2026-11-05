"""Lê o que o ffmpeg e os arquivos de descrição dos plugins dizem de cada um: funções puras sobre texto.

Os controles de um plugin vêm do próprio ffmpeg (`controls=help` nos filtros `lv2` e `ladspa`); o que o ffmpeg não imprime
(quantas portas de áudio um LV2 tem, o nome e os recursos que ele exige do hospedeiro) vem dos `.ttl` do pacote LV2, que são
a descrição que o plugin entrega com ele. Nada aqui abre arquivo ou executa algo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain.plugins import PluginControl

_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_LV2_CONTROL = re.compile(
    rf"\]\s+(?P<name>\S+)\s+<(?P<type>\w+)>\s+\(from (?P<low>{_NUMBER}) to (?P<high>{_NUMBER})\)\s+"
    rf"\(default (?P<default>{_NUMBER})\)\s*(?P<label>.*?)\s*$"
)
_LADSPA_CONTROL = re.compile(r"\]\s+c(?P<index>\d+): (?P<label>.*) \[<(?P<type>\w+)>(?P<rest>.*)\]\s*$")
_LADSPA_PLUGIN = re.compile(r"\]\s+(?P<inputs>\d+):(?P<outputs>\d+)\s+(?P<label>\S+)\s+(?P<name>.*?)\s*$")
_FFMPEG_FAILURE = re.compile(r"\[Parsed_\w+ @ [^\]]+\]\s*(?:Failed to|Could not|Unknown plugin|No such)")
# o que o próprio plugin reclama no stderr ("Options feature missing, cannot continue!") e o que o carregador de LV2 (lilv)
# imprime de ruído sobre as pastas vizinhas, que não é o motivo da falha
_PLUGIN_COMPLAINT = re.compile(r"missing|cannot|can't|unsupported|not supported|requires?", re.IGNORECASE)
_LOADER_NOISE = re.compile(
    r"lilv_|manifest\.ttl|load_dir_entry|failed to open file|Skipping|within path entry"
)


def _kind(type_name: str) -> str:
    """O tipo que o ffmpeg imprime (`float`, `int`, `toggled`) como o catálogo o chama."""
    return {"int": "integer", "toggled": "boolean", "bool": "boolean"}.get(type_name, "number")


def failure_line(text: str) -> str:
    """Por que o plugin não carregou, no relatório do ffmpeg: o que o próprio plugin reclamou e a linha do filtro, sem o prefixo
    `[Parsed_lv2_0 @ ...]`. Vazio quando não há falha. É o motivo que a varredura mostra."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ours = next((re.sub(r"^\[[^\]]*\]\s*", "", line) for line in lines if _FFMPEG_FAILURE.match(line)), "")
    theirs = next(
        (
            line
            for line in lines
            if not line.startswith("[") and _PLUGIN_COMPLAINT.search(line) and not _LOADER_NOISE.search(line)
        ),
        "",
    )
    return " | ".join(part for part in (theirs, ours) if part)


def parse_lv2_controls(text: str) -> list[PluginControl]:
    """Os controles de um LV2 no relatório de `lv2=...:c=help`. O nome é o símbolo da porta, que é como o filtro os aceita."""
    controls = []
    for line in text.splitlines():
        found = _LV2_CONTROL.search(line)
        if found is None:
            continue
        label = found["label"] or found["name"]
        controls.append(
            PluginControl(
                name=found["name"],
                label=label,
                default=float(found["default"]),
                minimum=float(found["low"]),
                maximum=float(found["high"]),
                kind=_kind(found["type"]),
            )
        )
    return controls


def parse_ladspa_controls(text: str) -> list[PluginControl]:
    """Os controles de um LADSPA no relatório de `ladspa=...:c=help`. O filtro só os aceita pela posição, então o nome é
    `c<N>` e o rótulo é o nome da porta que o plugin declara. Faixa ou padrão que o plugin não dá ficam vazios (o padrão, 0)."""
    controls = []
    for line in text.splitlines():
        found = _LADSPA_CONTROL.search(line)
        if found is None:
            continue
        rest = found["rest"]
        low = re.search(rf"min: ({_NUMBER})", rest)
        high = re.search(rf"max: ({_NUMBER})", rest)
        default = re.search(rf"default ({_NUMBER})", rest)
        minimum = float(low[1]) if low else None
        controls.append(
            PluginControl(
                name=f"c{found['index']}",
                label=found["label"],
                default=float(default[1]) if default else (minimum if minimum is not None else 0.0),
                minimum=minimum,
                maximum=float(high[1]) if high else None,
                kind=_kind(found["type"]),
            )
        )
    return controls


@dataclass(frozen=True)
class LadspaEntry:
    """Um plugin de uma biblioteca LADSPA, como `ladspa=f=<biblioteca>` o lista: o rótulo, o nome e as portas de áudio."""

    label: str
    name: str
    inputs: int
    outputs: int


def parse_ladspa_library(text: str) -> list[LadspaEntry]:
    """Os plugins que uma biblioteca LADSPA contém, no relatório de `ladspa=f=<biblioteca>` (sem `plugin`)."""
    entries = []
    listing = False
    for line in text.splitlines():
        if "library contains the following plugins" in line:
            listing = True
            continue
        if not listing:
            continue
        found = _LADSPA_PLUGIN.search(line)
        if found is not None:
            entries.append(
                LadspaEntry(found["label"], found["name"], int(found["inputs"]), int(found["outputs"]))
            )
    return entries


# ---------- os arquivos .ttl de um pacote LV2 ----------

_PREFIX = re.compile(r"@prefix\s+(\w*):\s*<([^>]*)>\s*\.")
_LV2_CORE = "http://lv2plug.in/ns/lv2core#"
# O que o filtro `lv2` do ffmpeg oferece ao plugin: o mapa de URIs (`urid:map`, `urid:unmap`). Os recursos do núcleo que não
# pedem nada do hospedeiro (tempo real, "ao vivo", buffers que não se sobrepõem) também passam. O que mais um plugin exigir
# (`options`, `worker`, `state`...) o ffmpeg não oferece: o plugin não instancia.
SUPPORTED_FEATURES = frozenset(
    {
        "http://lv2plug.in/ns/ext/urid#map",
        "http://lv2plug.in/ns/ext/urid#unmap",
        f"{_LV2_CORE}hardRTCapable",
        f"{_LV2_CORE}inPlaceBroken",
        f"{_LV2_CORE}isLive",
    }
)


def prefixes(ttl: str) -> dict[str, str]:
    """Os `@prefix` de um arquivo Turtle: nome curto para o endereço."""
    return {name: uri for name, uri in _PREFIX.findall(ttl)}


def _expand(token: str, known: dict[str, str]) -> str:
    """Um termo Turtle (`<uri>` ou `prefixo:nome`) como URI completa."""
    token = token.strip()
    if token.startswith("<") and token.endswith(">"):
        return token[1:-1]
    name, separator, local = token.partition(":")
    if separator and name in known:
        return known[name] + local
    return token


@dataclass(frozen=True)
class ManifestPlugin:
    """Um plugin declarado no `manifest.ttl` de um pacote: a URI, o arquivo binário e o `.ttl` que o descreve."""

    uri: str
    binary: str
    description: str


def manifest_plugins(manifest: str) -> list[ManifestPlugin]:
    """Os plugins que um `manifest.ttl` declara (os sujeitos do tipo `lv2:Plugin`, não os de interface gráfica)."""
    known = prefixes(manifest)
    plugins = []
    for block in _subject_blocks(manifest):
        types = re.search(r"(?:\ba\b|rdf:type)\s+(.+?)\s*[;.](?=\s|$)", block.body, re.DOTALL)
        names = {_expand(token, known) for token in re.split(r"\s*,\s*", types[1])} if types else set()
        if f"{_LV2_CORE}Plugin" not in names:
            continue
        binary = re.search(r"lv2:binary\s+<([^>]*)>", block.body)
        see = re.search(r"rdfs:seeAlso\s+<([^>]*)>", block.body)
        plugins.append(ManifestPlugin(block.subject, binary[1] if binary else "", see[1] if see else ""))
    return plugins


@dataclass(frozen=True)
class _Block:
    subject: str
    body: str


def _subject_blocks(ttl: str) -> list[_Block]:
    """Parte um Turtle nos sujeitos que começam no início da linha com uma URI (`<uri>`): o suficiente para os `.ttl` que os
    plugins entregam, em que o que vem indentado continua o sujeito de cima."""
    starts = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^<([^>\s]+)>", ttl)]
    blocks = []
    for position, (start, subject) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(ttl)
        blocks.append(_Block(subject, ttl[start:end]))
    return blocks


@dataclass(frozen=True)
class Lv2Description:
    """O que o `.ttl` de um plugin LV2 diz dele: nome, fabricante, portas de áudio e os recursos que ele exige do hospedeiro."""

    name: str
    maker: str
    audio_inputs: int
    audio_outputs: int
    required_features: tuple[str, ...]

    @property
    def unsupported_features(self) -> tuple[str, ...]:
        return tuple(feature for feature in self.required_features if feature not in SUPPORTED_FEATURES)


def describe_lv2(ttl: str, uri: str) -> Lv2Description:
    """A descrição do plugin `uri` no `.ttl` dele. Conta as portas de áudio pelo tipo de cada porta (`lv2:InputPort` ou
    `lv2:OutputPort`, junto de `lv2:AudioPort`)."""
    known = prefixes(ttl)
    body = next(
        (block.body for block in _subject_blocks(ttl) if block.subject == uri and "lv2:port" in block.body),
        "",
    )
    name = re.search(r'doap:name\s+"([^"]+)"', body)
    maker = re.search(r'foaf:name\s+"([^"]+)"', ttl)
    inputs = outputs = 0
    for types in re.findall(r"\ba\s+([^;\]]+?)\s*;", body):
        expanded = {_expand(token, known) for token in re.split(r"\s*,\s*", types)}
        if f"{_LV2_CORE}AudioPort" not in expanded:
            continue
        if f"{_LV2_CORE}InputPort" in expanded:
            inputs += 1
        elif f"{_LV2_CORE}OutputPort" in expanded:
            outputs += 1
    required: list[str] = []
    for listing in re.findall(r"lv2:requiredFeature\s+([^;]+?)\s*;", body, re.DOTALL):
        required += [_expand(token, known) for token in re.split(r"\s*,\s*", listing) if token.strip()]
    return Lv2Description(
        name=name[1] if name else uri,
        maker=maker[1] if maker else "",
        audio_inputs=inputs,
        audio_outputs=outputs,
        required_features=tuple(required),
    )

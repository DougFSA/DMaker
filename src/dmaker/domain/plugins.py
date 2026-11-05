"""Plugins de efeito de terceiros (LV2 e LADSPA): o que a varredura aprende de cada um e as contas puras sobre isso.

Quem lê o plugin é o ffmpeg (os filtros `lv2` e `ladspa` listam os controles com `controls=help`); aqui só ficam os dados
e as regras que não tocam disco: a identidade de um plugin, a forma de citá-lo na spec e a conferência dos parâmetros
contra a faixa que o próprio plugin declara. Tudo o que executa mora em `media.plugin_*` e `pipeline.plugins`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

PLUGIN_FORMATS = ("lv2", "ladspa")

# No LADSPA, "o plugin" é uma biblioteca com vários rótulos; a spec cita os dois juntos, `biblioteca.dll#rótulo`. O `#` nunca
# aparece num nome de arquivo do Windows, e separa sem ambiguidade (o `:` e a barra entrariam no caminho).
LADSPA_SEPARATOR = "#"

# O nome de um parâmetro na spec. No LV2 é o símbolo da porta (`delay_ms`); no LADSPA, o ffmpeg só aceita a posição, `c0`,
# `c1`..., e é assim que o catálogo os chama (o rótulo do plugin, "Atraso (ms)", fica no `label`).
PARAM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class PluginPorts:
    """Quantas portas de áudio o plugin tem. O construtor do grafo adapta o sinal estéreo do item a elas (um plugin mono
    roda uma vez por canal)."""

    inputs: int = 2
    outputs: int = 2


@dataclass(frozen=True)
class PluginControl:
    """Um controle do plugin como ele declara: nome na spec, rótulo, faixa e padrão. `kind` é `number`, `integer` ou
    `boolean` (o botão liga/desliga do LADSPA)."""

    name: str
    label: str
    default: float
    minimum: float | None = None
    maximum: float | None = None
    kind: str = "number"


@dataclass(frozen=True)
class PluginInfo:
    """Um plugin achado na varredura. `ref` é como a spec o cita (a URI do LV2, `arquivo#rótulo` no LADSPA); `path` é a pasta
    do pacote LV2 ou a biblioteca do LADSPA; `binary` é o arquivo que o ffmpeg carrega (o que muda quando o plugin é atualizado).
    `usable` é falso quando o ffmpeg não consegue hospedá-lo, e `problem` diz por quê."""

    format: str
    ref: str
    name: str
    path: str
    binary: str
    controls: tuple[PluginControl, ...] = ()
    ports: PluginPorts = field(default_factory=PluginPorts)
    maker: str = ""
    usable: bool = True
    problem: str = ""
    enabled: bool = True  # a escolha da pessoa (`plugins.json`), não da varredura

    @property
    def id(self) -> str:
        return plugin_id(self.format, self.ref)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["controls"] = list(data["controls"])  # o dado é JSON puro: lista, não tupla
        data["id"] = self.id
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginInfo:
        return cls(
            format=data["format"],
            ref=data["ref"],
            name=data["name"],
            path=data["path"],
            binary=data["binary"],
            controls=tuple(PluginControl(**control) for control in data.get("controls", [])),
            ports=PluginPorts(**data.get("ports", {})),
            maker=data.get("maker", ""),
            usable=data.get("usable", True),
            problem=data.get("problem", ""),
            enabled=data.get("enabled", True),
        )


def plugin_id(format_name: str, ref: str) -> str:
    """Um identificador curto e estável (`lv2-1a2b3c4d5e`) para rotas e comandos: a URI de um LV2 tem barras e dois-pontos."""
    return f"{format_name}-{hashlib.sha1(ref.encode('utf-8')).hexdigest()[:10]}"


def ladspa_ref(library: str, label: str) -> str:
    """A referência de um plugin LADSPA na spec: o nome do arquivo da biblioteca e o rótulo do plugin nela."""
    return f"{library}{LADSPA_SEPARATOR}{label}"


def split_ladspa_ref(ref: str) -> tuple[str, str]:
    """`(biblioteca, rótulo)` de uma referência LADSPA; erro com o formato certo quando falta uma das partes."""
    library, separator, label = ref.partition(LADSPA_SEPARATOR)
    if not separator or not library or not label:
        raise ValueError(
            f"plugin LADSPA {ref!r}: escreva o arquivo e o rótulo separados por {LADSPA_SEPARATOR!r}, "
            f"por exemplo 'cmt.dll{LADSPA_SEPARATOR}delay_5s'"
        )
    return library, label


def check_params(info: PluginInfo, params: dict[str, float]) -> list[str]:
    """O que há de errado nos `params` de um efeito contra os controles do plugin: nome que ele não tem e valor fora da faixa
    que ele declara. A faixa é do plugin (cada um tem a sua), por isso a spec não a conhece: quem chama decide se é aviso."""
    by_name = {control.name: control for control in info.controls}
    problems = []
    for name, value in params.items():
        control = by_name.get(name)
        if control is None:
            known = ", ".join(sorted(by_name)) or "nenhum"
            problems.append(f"o plugin {info.name!r} não tem o controle {name!r} (os dele: {known})")
            continue
        low, high = control.minimum, control.maximum
        if (low is not None and value < low) or (high is not None and value > high):
            span = f"{'' if low is None else f'{low:g}'} a {'' if high is None else f'{high:g}'}".strip()
            problems.append(f"{info.name}: {control.label} ({name}) vale de {span}; {value:g} está fora")
    return problems

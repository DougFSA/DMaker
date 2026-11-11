"""Os filtros `lv2` e `ladspa` do ffmpeg como texto de grafo, e os grafos de sondagem que listam o que um plugin expõe.
Funções puras: não executam nada nem tocam disco.

Escapar é o ponto delicado. O valor de uma opção de filtro passa por dois níveis de leitura: o do grafo (que lê aspas simples
como literal) e o do filtro (em que `\\` e `:` têm sentido). Por isso o valor vai entre aspas simples, com a barra e o
dois-pontos escapados para o segundo nível: a URI `urn:a:b` fica `'urn\\:a\\:b'`, e é isso que o ffmpeg lê de volta.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..domain.plugins import PluginPorts, split_ladspa_ref

# O ffmpeg do LADSPA só carrega por caminho se ele começa com `/` ou `.`; fora disso procura a biblioteca nas pastas de
# `LADSPA_PATH`, separadas por `:` (que no Windows racha `C:\...`) e com a extensão `.so`. Por isso o arquivo é citado como
# `./nome.dll` e o comando roda com a pasta da biblioteca como pasta de trabalho (`FFmpegCommand.cwd`).
LADSPA_LOCAL = "./"


def escape_option(value: str) -> str:
    """O valor de uma opção de filtro, seguro dentro de um grafo: entre aspas simples, com `\\` e `:` escapados."""
    if "'" in value:
        raise ValueError(f"valor de opção de filtro com aspas simples: {value!r}")
    return "'" + value.replace("\\", "\\\\").replace(":", "\\:") + "'"


def controls_text(params: Mapping[str, float]) -> str:
    """Os controles como o ffmpeg os lê: `nome=valor|nome=valor` (os dois formatos usam a mesma sintaxe; no LADSPA os nomes são
    `c0`, `c1`...). Vazio quando a spec não cita nenhum: o plugin usa o padrão dele."""
    return "|".join(f"{name}={format(value, '.9g')}" for name, value in sorted(params.items()))


def _filter(name: str, options: list[str]) -> str:
    return f"{name}=" + ":".join(options)


def lv2_filter(uri: str, params: Mapping[str, float]) -> str:
    """O filtro `lv2` de um plugin pela URI, com os controles."""
    options = [f"p={escape_option(uri)}"]
    controls = controls_text(params)
    if controls:
        options.append(f"c={escape_option(controls)}")
    return _filter("lv2", options)


def ladspa_filter(ref: str, params: Mapping[str, float]) -> str:
    """O filtro `ladspa` de um plugin (`biblioteca#rótulo`), com os controles. Roda com a pasta da biblioteca como pasta de
    trabalho do comando."""
    library, label = split_ladspa_ref(ref)
    options = [f"f={escape_option(LADSPA_LOCAL + library)}", f"p={escape_option(label)}"]
    controls = controls_text(params)
    if controls:
        options.append(f"c={escape_option(controls)}")
    return _filter("ladspa", options)


def plugin_lines(
    format_name: str,
    ref: str,
    params: Mapping[str, float],
    ports: PluginPorts,
    source: str,
    out: str,
    tag: str,
) -> list[str]:
    """As linhas do grafo que passam o sinal estéreo do item pelo plugin e o devolvem estéreo.

    O plugin diz quantas portas de áudio tem. Com duas entradas o sinal entra direto; com uma, o LADSPA roda uma instância por
    canal sozinho, e no LV2 o grafo separa os canais, passa cada um por uma instância e junta (dual mono, como o Audacity
    trata um plugin mono numa faixa estéreo). Uma saída só é copiada para os dois lados."""
    if format_name == "ladspa":
        return [f"{source}{ladspa_filter(ref, params)},aformat=channel_layouts=stereo{out}"]
    node = lv2_filter(ref, params)
    to_stereo = "pan=stereo|c0=c0|c1=c1"
    if ports.inputs >= 2:
        after = to_stereo if ports.outputs >= 2 else "pan=stereo|c0=c0|c1=c0"
        return [f"{source}{node},{after}{out}"]
    if (
        ports.outputs >= 2
    ):  # entra mono, sai estéreo (um reverb mono): mistura os canais e deixa o plugin abrir a imagem
        return [f"{source}pan=mono|c0=0.5*c0+0.5*c1,{node},{to_stereo}{out}"]
    left, right, left_out, right_out = (f"[{tag}_{name}]" for name in ("l", "r", "lo", "ro"))
    return [
        f"{source}channelsplit=channel_layout=stereo{left}{right}",
        f"{left}{node}{left_out}",
        f"{right}{node}{right_out}",
        f"{left_out}{right_out}amerge=inputs=2,{to_stereo}{out}",
    ]


# ---------- sondagem: o que o plugin expõe, lido pelo ffmpeg ----------


def lv2_help_graph(uri: str) -> str:
    """O grafo que faz o filtro `lv2` imprimir os controles do plugin (`controls=help`) e sair."""
    return f"lv2=p={escape_option(uri)}:c=help"


def ladspa_list_graph(library: str) -> str:
    """O grafo que faz o filtro `ladspa` listar os plugins de uma biblioteca (sem `plugin`)."""
    return f"ladspa=f={escape_option(LADSPA_LOCAL + library)}"


def ladspa_help_graph(library: str, label: str) -> str:
    """O grafo que faz o filtro `ladspa` imprimir os controles de um plugin da biblioteca."""
    return f"ladspa=f={escape_option(LADSPA_LOCAL + library)}:p={escape_option(label)}:c=help"

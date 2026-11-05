"""O efeito Plugin: qualquer plugin de efeito de terceiros no formato LV2 ou LADSPA (o que o Audacity carrega no menu
"Efeitos"), hospedado pelo ffmpeg.

A spec guarda só a referência e os valores: `format`, `plugin` (a URI do LV2, ou `arquivo#rótulo` no LADSPA) e `params`
(`{nome: número}`). Quais controles o plugin tem, com faixa e padrão, quem diz é o próprio plugin, lido pelo ffmpeg na
varredura (`dmaker audio plugins scan`), e por isso o catálogo desta classe não lista parâmetros por plugin: a interface
monta os controles da lista dos plugins instalados (`GET /api/audio-plugins`). Um parâmetro que a spec não cita fica com o
padrão do plugin.

O ffmpeg que hospeda o LV2 é outro (`bin/ffmpeg-lv2`), então o efeito roda num comando só dele, como um estágio da cadeia,
e não vale no áudio mestre.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import Field, model_validator

from ..plugins import PARAM_NAME, split_ladspa_ref
from .base import EffectBase, param, register_effect


@register_effect
class Plugin(EffectBase):
    """Aplica um plugin LV2 ou LADSPA instalado, com os valores dos controles dele."""

    type: Literal["plugin"] = "plugin"
    label: ClassVar[str] = "Plugin"
    audacity_name: ClassVar[str] = "Plugins LV2 e LADSPA"
    summary: ClassVar[str] = (
        "Aplica um plugin de efeito de terceiros (LV2 ou LADSPA) instalado nesta máquina, como no menu de efeitos do "
        "Audacity. Os controles vêm do próprio plugin."
    )
    separate_stage: ClassVar[bool] = True
    # só existe depois de escolher o plugin: o menu genérico da interface não o oferece, e quem o cria é a lista de plugins
    needs_selection: ClassVar[bool] = True

    format: Literal["lv2", "ladspa"] = param(
        "lv2", label="Formato", kind="plugin_format", hint="lv2 ou ladspa: o formato do plugin."
    )
    plugin: str = param(
        "",
        label="Plugin",
        kind="plugin",
        hint="A URI do plugin LV2, ou arquivo#rótulo no LADSPA (veja `dmaker audio plugins list`).",
    )
    params: dict[str, Annotated[float, Field(allow_inf_nan=False)]] = param(
        {},
        label="Controles",
        kind="plugin_params",
        hint="Os valores dos controles do plugin, {nome: número}. O que não está aqui fica com o padrão do plugin.",
    )

    @model_validator(mode="after")
    def _reference(self) -> Plugin:
        if not self.plugin.strip():
            raise ValueError("efeito plugin: diga qual plugin em `plugin` (veja `dmaker audio plugins list`)")
        if "'" in self.plugin or "\n" in self.plugin:
            raise ValueError(f"efeito plugin: {self.plugin!r} não é uma referência de plugin válida")
        if self.format == "ladspa":
            split_ladspa_ref(self.plugin)
        for name in self.params:
            if not PARAM_NAME.match(name):
                raise ValueError(
                    f"efeito plugin: {name!r} não é um nome de controle válido (letras, números e _)"
                )
        # a ordem das chaves não muda o som, e fora dela a chave de cache variaria com a ordem em que a pessoa escreveu
        self.params = {name: self.params[name] for name in sorted(self.params)}
        return self

    def host_format(self) -> str | None:
        return self.format

    def host_reference(self) -> str | None:
        return self.plugin

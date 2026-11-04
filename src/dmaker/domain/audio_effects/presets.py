"""Predefinições de efeitos de áudio: uma cadeia de efeitos já ajustada, posta no item de uma vez.

São dados puros. Predefinição e macro são a mesma estrutura (uma macro é a predefinição com nome, mais a saída opcional que só
vale ao aplicar a arquivos). Cada predefinição lista os efeitos (como a spec os escreve) que a operação `audio_effect` com a ação
`preset` acrescenta ao fim da cadeia do alvo, cada um como um efeito separado e editável depois: nada fica "preso" na
predefinição. O registro é `register_effect_preset`, e quem quer acrescentar outras (as macros do DMK-66) só registra
mais uma, sem tocar no catálogo, no MCP, na CLI nem na interface.

As cadeias são pontos de partida medidos em voz sintética (a medida está no manual): servem a quem não quer ajustar
cada parâmetro, e a pessoa ajusta o que precisar no efeito já posto.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import EFFECT_CLASSES


@dataclass(frozen=True)
class EffectPreset:
    """Uma predefinição, que também é uma macro: `id` (como a operação a cita), nome, uma frase do que faz e os efeitos
    da cadeia. `output` (o formato do arquivo e as escolhas de codificação, ver `macro_output`) só vale ao aplicar a
    macro a arquivos; aplicada a um item, a macro vira só a cadeia."""

    id: str
    label: str
    summary: str
    effects: tuple[dict, ...]
    # de onde vem: `builtin` (registrada no código) ou `user` (salva pela pessoa, em `user_presets`)
    origin: str = "builtin"
    output: dict | None = None
    # onde mora: `builtin`, `global` (a pasta de macros) ou `brand:<marca>` (a pasta de macros da marca)
    scope: str = "builtin"

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
            "effects": [dict(effect) for effect in self.effects],
            "origin": self.origin,
            "scope": self.scope,
        }
        if self.output:
            data["output"] = dict(self.output)
        return data


EFFECT_PRESETS: dict[str, EffectPreset] = {}


def register_effect_preset(preset: EffectPreset) -> EffectPreset:
    """Registra a predefinição pelo `id`. Um efeito que o catálogo não conhece, uma saída inválida ou um `id` repetido
    é erro na hora de importar: a predefinição nunca chega à pessoa quebrada."""
    from .macro_output import clean_output

    if preset.id in EFFECT_PRESETS:
        raise ValueError(f"Predefinição de efeitos já registrada: {preset.id}")
    unknown = sorted({effect["type"] for effect in preset.effects} - set(EFFECT_CLASSES))
    if unknown:
        raise ValueError(f"Predefinição {preset.id}: efeito(s) desconhecido(s): {', '.join(unknown)}")
    if clean_output(preset.output) != (preset.output or None):
        raise ValueError(f"Predefinição {preset.id}: a saída precisa vir já normalizada (clean_output)")
    EFFECT_PRESETS[preset.id] = preset
    return preset


def get_effect_preset(preset_id: str, brand: str | None = None) -> EffectPreset:
    """A predefinição de `id` dado: as embutidas primeiro e, não achando, as da marca (quando se diz a marca) e as
    globais que a pessoa salvou (a da marca já vem por cima da global de mesmo id)."""
    from .user_presets import load_user_presets

    if preset_id in EFFECT_PRESETS:
        return EFFECT_PRESETS[preset_id]
    saved = load_user_presets(brand)
    for preset in saved:
        if preset.id == preset_id:
            return preset
    known = ", ".join(sorted([*EFFECT_PRESETS, *(preset.id for preset in saved)]))
    raise ValueError(f"Predefinição desconhecida: {preset_id!r}. Use uma de: {known}")


def preset_catalog(brand: str | None = None) -> list[dict]:
    """As predefinições como o catálogo as entrega (`presets` de `catalog_payload`): as embutidas e, depois, as que a
    pessoa salvou (`origin: "user"`), as globais e, com a marca, as dela. A pasta é lida a cada chamada, então uma macro
    salva aparece na hora e sobrevive a reiniciar o programa."""
    from .user_presets import load_user_presets

    return [preset.to_dict() for preset in [*EFFECT_PRESETS.values(), *load_user_presets(brand)]]


def check_preset_fits(preset: EffectPreset, sample_stage_allowed: bool, place: str) -> None:
    """Recusa, com o motivo, a predefinição que tem um efeito que o lugar não aceita. O áudio mestre roda dentro do grafo
    ao vivo da mistura e não aceita os efeitos de amostras (o Noise Gate): a predefinição de voz vai no item de voz."""
    if sample_stage_allowed:
        return
    for effect in preset.effects:
        cls = EFFECT_CLASSES[effect["type"]]
        if cls.sample_stage:
            raise ValueError(
                f"a predefinição {preset.label!r} tem o efeito {cls.label}, que trabalha sobre as amostras do item e "
                f"não vale em {place}. Aplique no item de voz (narração, voz gravada ou trecho de vídeo)"
            )


register_effect_preset(
    EffectPreset(
        id="podcast_voice",
        label="Voz de podcast",
        summary="Gate leve, compressor 3:1, loudness a -16 LUFS e limitador a -1 dBTP: fala firme e pareada.",
        effects=(
            {"type": "noise_gate", "threshold_db": -50.0, "reduction_db": 12.0},
            {
                "type": "compressor",
                "threshold_db": -18.0,
                "ratio": 3.0,
                "knee_db": 6.0,
                "attack_ms": 15.0,
                "release_ms": 150.0,
            },
            {"type": "loudness_normalize", "mode": "lufs", "target_db": -16.0},
            {"type": "limiter", "ceiling_db": -1.0},
        ),
    )
)

register_effect_preset(
    EffectPreset(
        id="reels_voice",
        label="Voz de reels",
        summary="Compressor 4:1, loudness a -14 LUFS e limitador a -1 dBTP: fala alta e presente para o celular.",
        effects=(
            {
                "type": "compressor",
                "threshold_db": -20.0,
                "ratio": 4.0,
                "knee_db": 6.0,
                "attack_ms": 10.0,
                "release_ms": 120.0,
            },
            {"type": "loudness_normalize", "mode": "lufs", "target_db": -14.0},
            {"type": "limiter", "ceiling_db": -1.0},
        ),
    )
)

register_effect_preset(
    EffectPreset(
        id="hold_peaks",
        label="Segurar picos",
        summary="Limitador suave a -1 dBTP: nada passa do teto e os picos são abaixados com jeito.",
        effects=({"type": "limiter", "limit_type": "soft", "ceiling_db": -1.0},),
    )
)


# ---------- Fade Ajustável: os valores de partida ----------
#
# O Audacity oferece predefinições no Fade Ajustável (linear, exponencial, logarítmica, arredondada, cosseno e S, cada uma de
# entrada e de saída). Aqui são predefinições comuns: cada uma põe UM Fade Ajustável na cadeia, que a pessoa ajusta depois.
# O ajuste do meio entorta a forma (`domain.fade_curves`): +50 demora a abrir (parecido com o exponencial), -50 abre logo (parecido
# com o logarítmico).

_FADE_CASES: tuple[tuple[str, str, str, float, str], ...] = (
    # (id, nome, forma de entrada, ajuste do meio, forma de saída)
    ("linear", "Linear", "up", 0.0, "up"),
    ("exponential", "Exponencial", "up", 50.0, "down"),
    ("logarithmic", "Logarítmica", "up", -50.0, "down"),
    ("rounded", "Arredondada", "up", -25.0, "down"),
    ("cosine", "Cosseno", "sine_up", 0.0, "sine_down"),
    ("s_curve", "Curva em S", "s_up", 0.0, "s_down"),
)

for _id, _name, _shape_in, _mid, _shape_out in _FADE_CASES:
    register_effect_preset(
        EffectPreset(
            id=f"fade_{_id}_in",
            label=f"Fade Ajustável: {_name} (entrada)",
            summary=f"Abre do silêncio ao nível original, forma {_name.lower()}.",
            effects=(
                {
                    "type": "adjustable_fade",
                    "shape": _shape_in,
                    "mid_adjust": _mid,
                    "start_gain": 0.0,
                    "end_gain": 100.0,
                },
            ),
        )
    )
    register_effect_preset(
        EffectPreset(
            id=f"fade_{_id}_out",
            label=f"Fade Ajustável: {_name} (saída)",
            summary=f"Fecha do nível original ao silêncio, forma {_name.lower()}.",
            effects=(
                {
                    "type": "adjustable_fade",
                    "shape": _shape_out,
                    "mid_adjust": _mid,
                    "start_gain": 100.0,
                    "end_gain": 0.0,
                },
            ),
        )
    )

register_effect_preset(
    EffectPreset(
        id="fade_partial",
        label="Fade Ajustável: parcial (100% a 40%)",
        summary="Desce o volume a 40% (cerca de -8 dB) sem chegar ao silêncio: abaixa o som e o deixa audível.",
        effects=({"type": "adjustable_fade", "shape": "up", "start_gain": 100.0, "end_gain": 40.0},),
    )
)
register_effect_preset(
    EffectPreset(
        id="fade_soft_up",
        label="Fade Ajustável: subida suave (-12 dB a 0 dB)",
        summary="Sobe 12 dB em S, sem partir do silêncio: para trazer a música de volta depois de uma fala.",
        effects=(
            {"type": "adjustable_fade", "shape": "s_up", "start_gain": -12.0, "end_gain": 0.0, "unit": "db"},
        ),
    )
)
register_effect_preset(
    EffectPreset(
        id="fade_soft_down",
        label="Fade Ajustável: descida suave (0 dB a -12 dB)",
        summary="Desce 12 dB em S, sem chegar ao silêncio: para abrir espaço para uma fala.",
        effects=(
            {
                "type": "adjustable_fade",
                "shape": "s_down",
                "start_gain": 0.0,
                "end_gain": -12.0,
                "unit": "db",
            },
        ),
    )
)

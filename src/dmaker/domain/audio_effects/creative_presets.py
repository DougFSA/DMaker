"""As predefinições do Reverb (as do Audacity) e as de uso: voz de telefone, voz de rádio antigo, narração em sala e música etérea.

**Reverb.** Cada predefinição do Audacity põe um Reverb com valores de partida, e a pessoa ajusta o efeito já posto. O RT60 que
cada uma deve dar está em `REVERB_RT60_RANGES` (segundos, medido pelo decaimento de Schroeder de um clique seco, de -5 a -25 dB
extrapolado a -60): são faixas esperadas, medidas e conferidas por `tests/test_audio_delay_reverb_integration.py`, e a ordem
delas (banheiro e salas pequenas curtos, catedral longa) é a de um ouvido que conhece os nomes.

**De uso.** Cadeias prontas para os pedidos mais comuns:

- *Voz de telefone:* a banda de 300 Hz a 3,4 kHz (a mesma curva da predefinição `telephone`) e uma distorção suave, que é o que
  um microfone barato faz.
- *Voz de rádio antigo:* a curva do rádio AM, corte suave e um chiado leve (-52 dB).
- *Narração em sala:* um reverb de sala pequena, pouco molhado, que tira o "estúdio morto" de uma gravação seca.
- *Música etérea:* o Paulstretch de 8x e um reverb grande. O Paulstretch muda a duração e trabalha sobre as amostras, então vale
  só na música e na voz gravada, e a predefinição é recusada no master e nos itens que não podem crescer.

O pico de cada uma, sobre uma fala sintética normalizada a -1 dBFS, está no manual; nenhuma passa de 0 dBFS. Os ganhos molhado e
seco partem dos do Audacity; os da Vocal II, da Sala pequena escura e da Sala média foram abaixados em 0,5 a 1 dB para o pico
da fala sintética de teste ficar abaixo de -1 dBFS (a conta de energia do nosso reverb é diferente da dele).
"""

from __future__ import annotations

from .eq_presets import am_radio_curve, telephone_curve
from .presets import EffectPreset, register_effect_preset

# O RT60 esperado de cada predefinição do Reverb, em segundos (faixa baixa, faixa alta)
REVERB_RT60_RANGES: dict[str, tuple[float, float]] = {
    "reverb_vocal_1": (0.55, 0.9),
    "reverb_vocal_2": (0.5, 0.9),
    "reverb_bathroom": (0.65, 1.05),
    "reverb_small_room_bright": (0.3, 0.55),
    "reverb_small_room_dark": (0.35, 0.65),
    "reverb_medium_room": (0.55, 0.95),
    "reverb_large_room": (0.6, 1.0),
    "reverb_church_hall": (1.2, 1.9),
    "reverb_cathedral": (4.0, 6.0),
}

# (id, nome, resumo, tamanho da sala, pré-atraso, reverberância, amortecimento, tom grave, tom agudo, molhado, seco, largura)
_REVERBS: tuple[tuple[str, str, str, float, float, float, float, float, float, float, float, float], ...] = (
    (
        "reverb_vocal_1",
        "Reverb: Vocal I",
        "Um toque de sala para a voz, com os agudos amortecidos.",
        70,
        20,
        40,
        99,
        100,
        50,
        -12,
        0,
        70,
    ),
    (
        "reverb_vocal_2",
        "Reverb: Vocal II",
        "Como o Vocal I, com um pouco mais de sala.",
        60,
        20,
        50,
        99,
        100,
        50,
        -8.5,
        -0.5,
        70,
    ),
    (
        "reverb_bathroom",
        "Reverb: Banheiro",
        "Azulejo: reverberação curta, brilhante e sem graves.",
        16,
        8,
        80,
        0,
        0,
        100,
        -6,
        0,
        100,
    ),
    (
        "reverb_small_room_bright",
        "Reverb: Sala pequena clara",
        "Sala pequena, de paredes duras.",
        30,
        10,
        50,
        50,
        50,
        100,
        -1,
        -1,
        100,
    ),
    (
        "reverb_small_room_dark",
        "Reverb: Sala pequena escura",
        "Sala pequena, de paredes forradas.",
        30,
        10,
        50,
        50,
        100,
        0,
        -1.5,
        -1.5,
        100,
    ),
    (
        "reverb_medium_room",
        "Reverb: Sala média",
        "Uma sala de estar.",
        75,
        10,
        40,
        50,
        100,
        70,
        -1.5,
        -1.5,
        70,
    ),
    ("reverb_large_room", "Reverb: Sala grande", "Um auditório pequeno.", 85, 10, 40, 50, 100, 80, 0, -6, 90),
    (
        "reverb_church_hall",
        "Reverb: Salão de igreja",
        "Pé-direito alto e pedra: dois segundos de cauda.",
        90,
        32,
        60,
        50,
        100,
        50,
        0,
        -12,
        100,
    ),
    (
        "reverb_cathedral",
        "Reverb: Catedral",
        "O maior espaço: a cauda passa de quatro segundos.",
        90,
        32,
        100,
        50,
        100,
        50,
        0,
        -12,
        100,
    ),
)


def reverb_effect(
    room: float,
    pre_delay: float,
    reverberance: float,
    damping: float,
    tone_low: float,
    tone_high: float,
    wet_db: float,
    dry_db: float,
    width: float,
) -> dict:
    """Um efeito Reverb como a spec o escreve, com os valores do Audacity."""
    return {
        "type": "reverb",
        "room_size": float(room),
        "pre_delay_ms": float(pre_delay),
        "reverberance": float(reverberance),
        "damping": float(damping),
        "tone_low": float(tone_low),
        "tone_high": float(tone_high),
        "wet_db": float(wet_db),
        "dry_db": float(dry_db),
        "stereo_width": float(width),
    }


for _id, _label, _summary, *_values in _REVERBS:
    register_effect_preset(
        EffectPreset(id=_id, label=_label, summary=_summary, effects=(reverb_effect(*_values),))
    )

register_effect_preset(
    EffectPreset(
        id="phone_voice",
        label="Voz de telefone",
        summary="Só a faixa de 300 Hz a 3,4 kHz e uma distorção suave: a voz de uma ligação.",
        effects=(
            telephone_curve(),
            {
                "type": "distortion",
                "kind": "soft_clip",
                "drive_db": 6.0,
                "threshold_db": -6.0,
                "amount": 50.0,
            },
        ),
    )
)

register_effect_preset(
    EffectPreset(
        id="old_radio_voice",
        label="Voz de rádio antigo",
        summary="Curva de rádio AM, corte suave e um chiado leve: a voz de um rádio de válvula.",
        effects=(
            am_radio_curve(),
            {
                "type": "distortion",
                "kind": "soft_clip",
                "drive_db": 6.0,
                "threshold_db": -6.0,
                "amount": 70.0,
                "hiss_db": -52.0,
            },
        ),
    )
)

register_effect_preset(
    EffectPreset(
        id="room_narration",
        label="Narração em sala",
        summary="Reverb de sala pequena, pouco molhado: tira o ar de gravação seca sem virar eco.",
        effects=(reverb_effect(30, 10, 45, 55, 80, 100, -14, -1, 80),),
    )
)

register_effect_preset(
    EffectPreset(
        id="ethereal_music",
        label="Música etérea",
        summary="Paulstretch de 8x e reverb grande: a música vira uma textura longa. Só na música e na voz gravada.",
        effects=(
            {"type": "paulstretch", "stretch_factor": 8.0},
            reverb_effect(90, 32, 90, 40, 100, 70, -6, -60, 100),
        ),
    )
)

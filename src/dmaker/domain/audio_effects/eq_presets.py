"""As predefinições de equalização que o usuário do Audacity reconhece, registradas ao lado das de dinâmica.

Cada uma é uma cadeia de efeitos da família `eq` já ajustada: aumentar e cortar graves e agudos, telefone, rádio AM,
o ronco de 100 Hz e o zumbido da rede com os harmônicos (60 Hz no Brasil e nas Américas, 50 Hz na Europa). Entram no mesmo
catálogo, no mesmo `audio_effect` com `action: "preset"`, e a pessoa ajusta o efeito já posto.
"""

from __future__ import annotations

from .presets import EffectPreset, register_effect_preset

# O zumbido de uma rede de f Hz vem com os harmônicos inteiros dela: cinco entalhes estreitos (Q 30) tiram o grosso sem
# abrir buraco na voz, que tem pouca energia exatamente nessas frequências
HUM_HARMONICS = 5
HUM_Q = 30.0


def _hum(mains_hz: int) -> tuple[dict, ...]:
    return tuple(
        {"type": "notch", "frequency_hz": float(mains_hz * harmonic), "q": HUM_Q}
        for harmonic in range(1, HUM_HARMONICS + 1)
    )


register_effect_preset(
    EffectPreset(
        id="bass_boost",
        label="Aumentar graves",
        summary="Graves e agudos: +9 dB nos graves (prateleira em 250 Hz). Dá corpo a uma voz fina.",
        effects=({"type": "bass_treble", "bass_db": 9.0},),
    )
)

register_effect_preset(
    EffectPreset(
        id="bass_cut",
        label="Cortar graves",
        summary="Prateleira de graves de -9 dB abaixo de 200 Hz. Tira o embolado de uma gravação de celular.",
        effects=({"type": "low_shelf", "frequency_hz": 200.0, "gain_db": -9.0},),
    )
)

register_effect_preset(
    EffectPreset(
        id="treble_boost",
        label="Aumentar agudos",
        summary="Graves e agudos: +9 dB nos agudos (prateleira em 4 kHz). Dá brilho e clareza a uma voz abafada.",
        effects=({"type": "bass_treble", "treble_db": 9.0},),
    )
)

register_effect_preset(
    EffectPreset(
        id="treble_cut",
        label="Cortar agudos",
        summary="Prateleira de agudos de -9 dB acima de 4 kHz. Suaviza o chiado e a aspereza.",
        effects=({"type": "high_shelf", "frequency_hz": 4000.0, "gain_db": -9.0},),
    )
)


def telephone_curve() -> dict:
    """O EQ por curva do telefone (300 Hz a 3,4 kHz), que a voz de telefone das predefinições de uso reaproveita."""
    return {
        "type": "filter_curve_eq",
        "points": [
            {"hz": 20.0, "db": -40.0},
            {"hz": 200.0, "db": -30.0},
            {"hz": 300.0, "db": 0.0},
            {"hz": 3400.0, "db": 0.0},
            {"hz": 4200.0, "db": -30.0},
            {"hz": 20000.0, "db": -40.0},
        ],
        "interpolation": "cosine",
    }


def am_radio_curve() -> dict:
    """O EQ por curva do rádio AM, que a voz de rádio antigo reaproveita."""
    return {
        "type": "filter_curve_eq",
        "points": [
            {"hz": 20.0, "db": -40.0},
            {"hz": 120.0, "db": -26.0},
            {"hz": 250.0, "db": -4.0},
            {"hz": 600.0, "db": 0.0},
            {"hz": 2500.0, "db": 2.0},
            {"hz": 4500.0, "db": -8.0},
            {"hz": 6000.0, "db": -32.0},
            {"hz": 20000.0, "db": -40.0},
        ],
        "interpolation": "cosine",
    }


register_effect_preset(
    EffectPreset(
        id="telephone",
        label="Telefone",
        summary="EQ por curva que deixa só a faixa de 300 Hz a 3,4 kHz, como numa ligação.",
        effects=(telephone_curve(),),
    )
)

register_effect_preset(
    EffectPreset(
        id="am_radio",
        label="Rádio AM",
        summary="EQ por curva de faixa estreita, com um realce de 2 dB nos médios, como um rádio AM antigo.",
        effects=(am_radio_curve(),),
    )
)

register_effect_preset(
    EffectPreset(
        id="rumble_100hz",
        label="Ronco de 100 Hz",
        summary="Passa-alta de 100 Hz a 24 dB por oitava: tira o ronco de ar-condicionado, vento e manuseio do microfone.",
        effects=({"type": "highpass", "frequency_hz": 100.0, "slope_db": 24},),
    )
)

register_effect_preset(
    EffectPreset(
        id="hum_60hz",
        label="Zumbido 60 Hz e harmônicos",
        summary="Notches estreitos em 60, 120, 180, 240 e 300 Hz: tiram o zumbido da rede elétrica sem mexer na voz.",
        effects=_hum(60),
    )
)

register_effect_preset(
    EffectPreset(
        id="hum_50hz",
        label="Zumbido 50 Hz e harmônicos",
        summary="Notches estreitos em 50, 100, 150, 200 e 250 Hz: o zumbido da rede de 50 Hz (Europa e outros países).",
        effects=_hum(50),
    )
)

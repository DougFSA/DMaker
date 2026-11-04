"""As macros embutidas: receitas de tratamento prontas, equivalentes às Macros do Audacity (Tools, Macros).

São predefinições comuns (`register_effect_preset`) que, além da cadeia, podem trazer a saída (`output`) que vale ao
aplicá-las a uma pasta de arquivos (`dmaker audio macro run`). Aplicadas a um item, viram só a cadeia, editável depois.
Os valores são pontos de partida medidos em voz sintética (as medidas estão no manual).
"""

from __future__ import annotations

from .presets import EffectPreset, register_effect_preset

register_effect_preset(
    EffectPreset(
        id="mp3_standard",
        label="MP3 para o padrão",
        summary="Normaliza o pico a -1 dBFS (e tira o desvio de nível) e grava em MP3: a conversão de sempre, em lote.",
        effects=({"type": "normalize", "peak_db": -1.0},),
        output={"preset": "audio/mp3"},
    )
)

register_effect_preset(
    EffectPreset(
        id="ends_fade",
        label="Fade nas pontas",
        summary="Entrada de 0,3 s e saída de 0,6 s: tira o estalo do começo e do fim do arquivo.",
        effects=(
            {"type": "fade_in", "duration": 0.3},
            {"type": "fade_out", "duration": 0.6},
        ),
    )
)

register_effect_preset(
    EffectPreset(
        id="clean_narration",
        label="Limpar narração",
        summary=(
            "Passa-alta a 80 Hz (tira o ronco), Redução de ruído automática, compressor suave, loudness a -16 LUFS "
            "e limitador a -1 dBTP: fala limpa e no volume de entrega."
        ),
        effects=(
            {"type": "highpass", "frequency_hz": 80.0, "slope_db": 12},
            {"type": "noise_reduction", "reduction_db": 12.0, "sensitivity": 6.0, "smoothing_bands": 3},
            {
                "type": "compressor",
                "threshold_db": -20.0,
                "ratio": 2.5,
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
        id="clean_phone_recording",
        label="Limpar gravação de celular",
        summary=(
            "Passa-alta a 80 Hz, tira estalos, Redução de ruído automática (12, 6, 3), Noise Gate leve e normaliza o "
            "pico a -1 dBFS: a receita para áudio de WhatsApp e gravação de celular."
        ),
        effects=(
            {"type": "highpass", "frequency_hz": 80.0, "slope_db": 12},
            {"type": "click_removal"},
            {"type": "noise_reduction", "reduction_db": 12.0, "sensitivity": 6.0, "smoothing_bands": 3},
            {"type": "noise_gate", "threshold_db": -50.0, "reduction_db": 12.0},
            {"type": "normalize", "peak_db": -1.0},
        ),
    )
)

"""A saída de uma macro: o formato do arquivo (`audio/mp3`...) e as escolhas de codificação, validados sem a spec.

Só vale ao aplicar a macro a arquivos (`dmaker audio macro run`): aplicada a um item, a macro vira só a cadeia de efeitos.
Fica à parte da spec (`Output.audio_format`) porque o pacote de efeitos é importado pela spec, e importar a spec daqui
fechava um ciclo; por isso as escolhas são conferidas pelo próprio `resolve_encoding`, que é quem as recusa no render.
"""

from __future__ import annotations

from typing import Any

from ..audio_presets import (
    AudioFormatError,
    EncodingChoices,
    get_audio_preset,
    is_audio_preset,
    resolve_encoding,
)

# o que a macro pode escolher da codificação: os mesmos campos de `AudioFormat` (domain/spec.py)
CHOICE_FIELDS = ("sample_rate", "channels", "bit_depth", "bitrate_mode", "bitrate_k", "quality")


def clean_output(raw: Any) -> dict[str, Any] | None:
    """A saída validada e normalizada (`{"preset": "audio/mp3", "bitrate_k": 192}`), ou `None` quando não há saída.

    `preset` aceita o id (`audio/mp3`) ou o apelido (`mp3`); o que o formato não aceita (24 bits num MP3) é recusado
    aqui, na hora de salvar, e não só quando a macro for aplicada a uma pasta inteira."""
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            'a saída da macro é um objeto, por exemplo {"preset": "audio/mp3", "bitrate_k": 192}'
        )
    unknown = sorted(set(raw) - {"preset", *CHOICE_FIELDS})
    if unknown:
        raise ValueError(f"saída da macro com campo desconhecido: {', '.join(unknown)}")
    name = raw.get("preset")
    if not isinstance(name, str) or not is_audio_preset(name):
        raise ValueError(
            "a saída da macro precisa de `preset`, um formato de áudio (audio/mp3, audio/wav, audio/flac...)"
        )
    preset = get_audio_preset(name)
    choices = {field: raw[field] for field in CHOICE_FIELDS if raw.get(field) is not None}
    try:
        resolve_encoding(preset, EncodingChoices(**choices))
    except (AudioFormatError, TypeError) as exc:
        raise ValueError(f"saída da macro inválida: {exc}") from exc
    return {"preset": preset.id, **choices}


def output_choices(output: dict[str, Any] | None) -> EncodingChoices | None:
    """As escolhas de codificação da saída da macro (`None` quando não escolhe nenhuma: vale o padrão do formato)."""
    if not output:
        return None
    choices = EncodingChoices(**{field: output[field] for field in CHOICE_FIELDS if field in output})
    return None if choices.empty else choices

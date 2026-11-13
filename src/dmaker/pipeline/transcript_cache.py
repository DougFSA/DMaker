"""Cache da transcrição automática (`captions.auto.json`): quando a transcrição guardada ainda vale para a fala da
linha do tempo e como reaproveitá-la sem perder as correções feitas à mão, pelo `fix_captions` ou pela interface."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import ClipSegment, Segment
from ..domain.timeline import segment_duration, timeline_spans, transitions_of
from ..text.captions import Cue, follow_moves, from_json, to_json, to_srt
from .cache_key import cache_key
from .sources import Source

# muda quando o que decide a chave muda. v2: a linha do tempo inteira (cartões inclusive);
# v3: só os clipes, que são os trechos com som, e o instante em que cada um toca no vídeo final
TRANSCRIPT_CACHE_VERSION = "v3"

Span = tuple[float, float]


@dataclass(frozen=True)
class SpeechLayout:
    """O que se ouve na linha do tempo (os clipes, na ordem, com a fonte de cada um) e onde cada clipe toca."""

    clips: list[object]
    spans: list[Span]


def speech_layout(timeline: Sequence[Segment], sources: Sequence[Source]) -> SpeechLayout:
    """Cartões e imagens não têm som: só entram pelo deslocamento que causam nos clipes (transições incluídas),
    então trocar o título de um cartão ou acrescentar um no fim não muda nada aqui."""
    durations = [
        segment_duration(seg, src.info, src.offset) for seg, src in zip(timeline, sources, strict=True)
    ]
    spans = timeline_spans(durations, transitions_of(list(timeline)))
    clips: list[object] = []
    clip_spans: list[Span] = []
    for seg, src, duration, (start, end) in zip(timeline, sources, durations, spans, strict=True):
        if not isinstance(seg, ClipSegment):
            continue
        # o arredondamento (microssegundo) tira o ruído de ponto flutuante da soma das durações da chave
        clips.append((seg.model_dump(mode="json"), str(src.path), src.stat_key(), round(duration, 6)))
        clip_spans.append((round(start, 6), round(end, 6)))
    return SpeechLayout(clips, clip_spans)


@dataclass(frozen=True)
class TranscriptKeys:
    """As chaves que dizem se a transcrição guardada vale. `exact` é a fala e o lugar de cada clipe; `speech`, só a
    fala, que decide se dá para deslocar as legendas em vez de transcrever. `movable` é falso quando há voz que não
    anda com os clipes (os arquivos de `audio.voiceover` tocam em instantes fixos). `legacy` é a chave v2, para
    aceitar sem transcrever o arquivo gravado antes desta versão."""

    exact: str
    speech: str
    spans: list[Span]
    movable: bool
    legacy: str | None = None


def transcript_keys(
    layout: SpeechLayout, settings: Sequence[object], *, movable: bool, legacy: str | None = None
) -> TranscriptKeys:
    speech = cache_key(TRANSCRIPT_CACHE_VERSION, layout.clips, list(settings))
    return TranscriptKeys(cache_key(speech, layout.spans), speech, layout.spans, movable, legacy)


@dataclass(frozen=True)
class CachedTranscript:
    """Legendas reaproveitadas. `rewrite` diz que o arquivo precisa ser regravado com a chave atual (as legendas
    foram deslocadas, ou o arquivo veio do formato anterior)."""

    cues: list[Cue]
    rewrite: bool


def cues_fingerprint(cues: Sequence[Cue]) -> str:
    """Impressão digital do texto e dos tempos: a gravada junto com a transcrição deixa de bater quando alguém edita."""
    return cache_key(
        [
            (
                float(cue.start),
                float(cue.end),
                cue.text,
                [(float(w.start), float(w.end), w.text, w.probability) for w in cue.words],
            )
            for cue in cues
        ]
    )


def was_edited(data: dict) -> bool:
    """As legendas do arquivo foram mexidas depois da transcrição. Sem a impressão digital (arquivo de antes desta
    versão, ou já deslocado depois de editado) não há como saber, e na dúvida conta como editado."""
    stamp = data.get("cues_hash")
    return stamp is None or stamp != cues_fingerprint(from_json(json.dumps(data)))


def reuse(data: dict, keys: TranscriptKeys) -> CachedTranscript | None:
    """As legendas do arquivo, se valem para a fala atual: as mesmas, se nada que se ouve mudou; deslocadas junto
    com cada clipe, se só mudou onde os clipes tocam; None se a fala mudou e é preciso transcrever de novo."""
    stored = data.get("hash")
    if stored == keys.exact:
        return CachedTranscript(from_json(json.dumps(data)), rewrite=False)
    if keys.legacy is not None and stored == keys.legacy:
        return CachedTranscript(from_json(json.dumps(data)), rewrite=True)
    old_spans = data.get("spans")
    if not keys.movable or data.get("speech") != keys.speech or not isinstance(old_spans, list):
        return None
    if len(old_spans) != len(keys.spans):
        return None
    moves = [(old[0], old[1], new[0] - old[0]) for old, new in zip(old_spans, keys.spans, strict=True)]
    return CachedTranscript(follow_moves(from_json(json.dumps(data)), moves), rewrite=True)


def transcript_record(
    cues: list[Cue], language: str, keys: TranscriptKeys, meta: object, *, edited: bool
) -> dict:
    """O conteúdo de `captions.auto.json`. A impressão digital só vai quando as legendas são as da transcrição:
    legendas editadas continuam contando como editadas depois de deslocadas."""
    record = json.loads(to_json(cues, language))
    record.update({"hash": keys.exact, "speech": keys.speech, "spans": [list(span) for span in keys.spans]})
    if not edited:
        record["cues_hash"] = cues_fingerprint(cues)
    record["meta"] = meta
    return record


class TranscriptStore:
    """O arquivo da transcrição de um projeto (e o `.srt` ao lado): a única parte deste módulo que toca o disco."""

    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def lookup(self, keys: TranscriptKeys) -> tuple[CachedTranscript, dict] | None:
        data = self.read()
        if data is None:
            return None
        try:
            cached = reuse(data, keys)
        except (KeyError, ValueError, TypeError, IndexError):
            return None
        return (cached, data) if cached is not None else None

    def save(self, record: dict, cues: list[Cue]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        self.path.with_suffix(".srt").write_text(to_srt(cues), encoding="utf-8")

    def keep_edited(self) -> Path | None:
        """Guarda ao lado a versão editada antes de uma transcrição nova gravar por cima, e diz onde ficou. O nome
        sai das próprias legendas: a mesma edição guardada duas vezes não vira dois arquivos."""
        data = self.read()
        if data is None or not data.get("cues") or not was_edited(data):
            return None
        stamp = cues_fingerprint(from_json(json.dumps(data)))[:8]
        backup = self.path.with_name(f"{self.path.stem}.editado-{stamp}.json")
        shutil.copyfile(self.path, backup)
        return backup

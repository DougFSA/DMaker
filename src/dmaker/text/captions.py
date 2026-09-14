"""Legendas como dados: cues com tempo por palavra, leitura/escrita de SRT e JSON,
reagrupamento em linhas curtas (estilo Reels), correção de palavras e detecção de cues suspeitas.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

SENTENCE_END = re.compile(r"[.!?…]$")
CLAUSE_END = re.compile(r"[,;:]$")
PUNCT = ".,;:!?\"'()"


@dataclass
class Word:
    start: float
    end: float
    text: str
    probability: float | None = None  # confiança do modelo (0..1); None em legendas sem Whisper


@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


# ---------- SRT ----------


def _parse_ts(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, (m, s) = "0", parts
    else:
        return float(value)
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_srt(text: str) -> list[Cue]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n{2,}", text.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
            lines = lines[1:]
        if "-->" not in lines[0]:
            continue
        a, b = lines[0].split("-->")[:2]
        b = b.strip().split(" ")[0]
        body = " ".join(ln.strip() for ln in lines[1:])
        body = re.sub(r"<[^>]+>", "", body)  # tags de formatação
        if body:
            cues.append(Cue(_parse_ts(a), _parse_ts(b), body))
    return cues


def _fmt_srt(seconds: float) -> str:
    ms = int(round(max(seconds, 0) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    out = []
    for i, c in enumerate(cues, 1):
        out.append(f"{i}\n{_fmt_srt(c.start)} --> {_fmt_srt(c.end)}\n{c.text}\n")
    return "\n".join(out)


# ---------- JSON com tempo por palavra ----------


def to_json(cues: list[Cue], language: str = "pt") -> str:
    return json.dumps({"language": language, "cues": [asdict(c) for c in cues]}, ensure_ascii=False, indent=1)


def from_json(text: str) -> list[Cue]:
    data = json.loads(text)
    cues = []
    for c in data.get("cues", []):
        words = [
            Word(
                float(w["start"]),
                float(w["end"]),
                str(w["text"]),
                float(w["probability"]) if w.get("probability") is not None else None,
            )
            for w in c.get("words", [])
        ]
        cues.append(Cue(float(c["start"]), float(c["end"]), str(c["text"]), words))
    return cues


def load_captions(path: Path) -> list[Cue]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return from_json(text)
    if path.suffix.lower() == ".vtt":
        text = re.sub(r"^WEBVTT.*?\n\n", "", text, flags=re.S)
    return parse_srt(text)


def save_captions(cues: list[Cue], path: Path, language: str = "pt") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = to_json(cues, language) if path.suffix.lower() == ".json" else to_srt(cues)
    path.write_text(content, encoding="utf-8")
    return path


# ---------- reagrupamento ----------


def flatten_words(cues: list[Cue]) -> list[Word]:
    """Lista de palavras com tempo. Sem tempo por palavra, distribui a duração da cue proporcionalmente."""
    words: list[Word] = []
    for cue in cues:
        if cue.words:
            words.extend(Word(w.start, w.end, w.text.strip()) for w in cue.words if w.text.strip())
            continue
        tokens = cue.text.split()
        if not tokens:
            continue
        total_chars = sum(len(t) for t in tokens)
        t = cue.start
        for tok in tokens:
            share = cue.duration * (len(tok) / total_chars) if total_chars else cue.duration / len(tokens)
            words.append(Word(t, min(t + share, cue.end), tok))
            t += share
    return words


def regroup(
    cues: list[Cue],
    max_words: int = 4,
    max_chars: int = 22,
    max_gap: float = 0.8,
    min_duration: float = 0.5,
    hold_gap: float = 0.6,
) -> list[Cue]:
    """Quebra em linhas curtas: por quantidade de palavras, caracteres, pontuação e pausas."""
    words = flatten_words(cues)
    lines: list[Cue] = []
    current: list[Word] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(w.text for w in current)
        lines.append(Cue(current[0].start, current[-1].end, text, list(current)))
        current.clear()

    for w in words:
        if current:
            gap = w.start - current[-1].end
            length = len(" ".join(x.text for x in current)) + 1 + len(w.text)
            if (
                len(current) >= max_words
                or length > max_chars
                or gap > max_gap
                or SENTENCE_END.search(current[-1].text)
                or (CLAUSE_END.search(current[-1].text) and len(current) >= 2)
            ):
                flush()
        current.append(w)
    flush()

    # duração mínima legível e pausas curtas seguradas, sem invadir a linha seguinte
    for i, line in enumerate(lines):
        nxt = lines[i + 1].start if i + 1 < len(lines) else None
        if line.duration < min_duration:
            limit = nxt if nxt is not None else line.start + min_duration
            line.end = max(line.end, min(line.start + min_duration, limit))
        if nxt is not None and 0 < nxt - line.end <= hold_gap:
            line.end = nxt
    return lines


def apply_replacements(cues: list[Cue], replacements: dict[str, str]) -> list[Cue]:
    """Corrige palavras ouvidas errado (comparação sem acento/caixa), preservando pontuação ao redor."""
    if not replacements:
        return cues
    table = {fold(k): v for k, v in replacements.items()}

    def fix(token: str) -> str:
        core = token.strip(PUNCT)
        if not core:
            return token
        repl = table.get(fold(core))
        return token.replace(core, repl) if repl else token

    def fix_pairs(words: list[Word]) -> list[Word]:
        merged: list[Word] = []
        i = 0
        while i < len(words):
            if i + 1 < len(words):
                a, b = words[i], words[i + 1]
                pair = fold(a.text.strip(PUNCT) + " " + b.text.strip(PUNCT))
                if pair in table:
                    tail = b.text[len(b.text.rstrip(PUNCT)) :]
                    merged.append(Word(a.start, b.end, table[pair] + tail))
                    i += 2
                    continue
            merged.append(words[i])
            i += 1
        return merged

    out: list[Cue] = []
    for c in cues:
        words = fix_pairs([Word(w.start, w.end, fix(w.text)) for w in c.words])
        if words:
            text = " ".join(w.text for w in words)
        else:
            text = " ".join(w.text for w in fix_pairs([Word(0, 0, fix(t)) for t in c.text.split()]))
        out.append(Cue(c.start, c.end, text, words))
    return out


def fold(text: str) -> str:
    """Minúsculas e sem acento, para comparar palavras ouvidas com o vocabulário da marca."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def edit_distance(a: str, b: str) -> int:
    """Distância de Levenshtein: quantas edições separam duas palavras (0 = iguais)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def shift(cues: list[Cue], offset: float) -> list[Cue]:
    out = []
    for c in cues:
        out.append(
            Cue(
                c.start + offset,
                c.end + offset,
                c.text,
                [Word(w.start + offset, w.end + offset, w.text, w.probability) for w in c.words],
            )
        )
    return out


# ---------- cues suspeitas (para revisão sem reler tudo) ----------


@dataclass
class CueIssue:
    index: int
    start: float
    end: float
    text: str
    reasons: list[str]
    words_low: list[str] = field(default_factory=list)  # palavras com confiança abaixo do limite


def _clean(token: str) -> str:
    return token.strip(PUNCT)


def _pending_replacements(words: list[Word], table: dict[str, str]) -> list[str]:
    """Pares/palavras ouvidas que batem com uma chave de `replacements` ainda não aplicada ao arquivo."""
    texts = [_clean(w.text) for w in words]
    found: list[str] = []
    i = 0
    while i < len(texts):
        if i + 1 < len(texts):
            pair_key = fold(f"{texts[i]} {texts[i + 1]}")
            if pair_key in table:
                found.append(f"{texts[i]} {texts[i + 1]} -> {table[pair_key]}")
                i += 2
                continue
        single_key = fold(texts[i]) if texts[i] else ""
        if single_key and single_key in table:
            found.append(f"{texts[i]} -> {table[single_key]}")
        i += 1
    return found


def _brand_term_matches(heard: set[str], vocabulary: list[str]) -> list[str]:
    """Palavras ouvidas parecidas (distância de edição <= 2) com um termo do vocabulário da marca."""
    matches: list[str] = []
    for term in vocabulary:
        folded_term = fold(term)
        for word in heard:
            if not word:
                continue
            folded_word = fold(word)
            if folded_word == folded_term or abs(len(folded_word) - len(folded_term)) > 2:
                continue
            if edit_distance(folded_word, folded_term) <= 2:
                matches.append(f"{word} -> {term}")
    return matches


def suspicious_cues(
    cues: list[Cue],
    vocabulary: list[str] | None = None,
    replacements: dict[str, str] | None = None,
    *,
    min_probability: float = 0.6,
    max_chars: int = 44,
    max_duration: float = 7.0,
    min_duration: float = 0.3,
) -> list[CueIssue]:
    """Cues que merecem uma olhada: palavra com baixa confiança, cue longa/curta, termo da marca ouvido
    errado ou substituição pendente. Pura: só lê `cues`, não toca disco nem chama o Whisper."""
    vocabulary = vocabulary or []
    table = {fold(k): v for k, v in (replacements or {}).items()}
    issues: list[CueIssue] = []
    for i, cue in enumerate(cues):
        reasons: list[str] = []
        words_low: list[str] = []
        for w in cue.words:
            if w.probability is not None and w.probability < min_probability:
                word = _clean(w.text)
                reasons.append(f"palavra com baixa confiança: {word} ({w.probability:.2f})")
                words_low.append(word)
        if len(cue.text) > max_chars:
            reasons.append(f"cue longa ({len(cue.text)} caracteres)")
        duration = cue.end - cue.start
        if duration < min_duration:
            reasons.append(f"cue curta ({duration:.2f}s)")
        elif duration > max_duration:
            reasons.append(f"cue longa ({duration:.1f}s)")
        heard = {_clean(w.text) for w in cue.words if w.text.strip()}
        for match in _brand_term_matches(heard, vocabulary):
            reasons.append(f"parece termo da marca: {match}")
        for pending in _pending_replacements(cue.words, table):
            reasons.append(f"substituição pendente: {pending}")
        if reasons:
            issues.append(CueIssue(i, cue.start, cue.end, cue.text, reasons, words_low))
    return issues


def captions_digest(cues: list[Cue]) -> dict:
    """Resumo barato das legendas: contagem, duração coberta, palavras, confiança média e as pontas."""
    total_words = sum(len(c.words) if c.words else len(c.text.split()) for c in cues)
    covered = sum(c.end - c.start for c in cues)
    probabilities = [w.probability for c in cues for w in c.words if w.probability is not None]
    avg_probability = sum(probabilities) / len(probabilities) if probabilities else None
    return {
        "total_cues": len(cues),
        "covered_duration_s": round(covered, 1),
        "total_words": total_words,
        "avg_probability": round(avg_probability, 2) if avg_probability is not None else None,
        "first_cues": [c.text for c in cues[:2]],
        "last_cues": [c.text for c in cues[-2:]],
    }

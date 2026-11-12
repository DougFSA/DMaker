"""O processo que desenha a persona realista: `python -m dmaker.media.ditto_worker <opções>`.

Roda num processo à parte por três motivos: o torch e o OpenVINO disputam threads com o resto do DMaker, o hubert
sozinho ocupa 1,4 GB de memória e uma falha de driver de vídeo derrubaria o servidor da interface. A conversa com
quem o chamou (`DittoTalkingHead`) é por linhas de texto no stdout, uma por evento:

    ETAPA <texto>                    o que está fazendo agora
    DISPOSITIVO <texto>              onde as contas rodam (GPU integrada ou CPU)
    AVISO <texto>                    algo que o usuário deve saber
    QUADRO <i> <n> <caminho>         o quadro i de n (a partir de 1) está pronto, em RGB cru, nesse arquivo
    PRONTO <n> <segundos>            terminou; n quadros em tantos segundos
    ERRO <texto>                     falhou (o processo sai com código diferente de zero)

Os quadros vão por arquivo, e não pelo stdout, para que um texto perdido no meio nunca corrompa uma imagem.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

EMIT = Callable[[str], None]


@dataclass(frozen=True)
class WorkerArguments:
    models_dir: Path  # a pasta `cache/models`
    cache_dir: Path  # onde o OpenVINO guarda os kernels compilados
    photo: Path  # a foto já enquadrada no tamanho final do quadro
    audio: Path
    frames_dir: Path  # onde cada quadro é escrito até quem chamou o ler
    duration: float
    seed: int
    steps: int

    def to_command(self) -> list[str]:
        """A linha de comando que o `DittoTalkingHead` lança (a mesma que `parse_arguments` lê de volta)."""
        return [
            "--models-dir",
            str(self.models_dir),
            "--cache-dir",
            str(self.cache_dir),
            "--photo",
            str(self.photo),
            "--audio",
            str(self.audio),
            "--frames-dir",
            str(self.frames_dir),
            "--duration",
            repr(self.duration),
            "--seed",
            str(self.seed),
            "--steps",
            str(self.steps),
        ]


def parse_arguments(argv: list[str]) -> WorkerArguments:
    parser = argparse.ArgumentParser(prog="dmaker.media.ditto_worker", description=__doc__)
    for name in ("models-dir", "cache-dir", "photo", "audio", "frames-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--steps", type=int, required=True)
    values = parser.parse_args(argv)
    return WorkerArguments(
        models_dir=values.models_dir,
        cache_dir=values.cache_dir,
        photo=values.photo,
        audio=values.audio,
        frames_dir=values.frames_dir,
        duration=values.duration,
        seed=values.seed,
        steps=values.steps,
    )


def format_event(kind: str, *fields: object) -> str:
    return " ".join([kind, *(str(field) for field in fields)])


def load_speech(path: Path, duration: float) -> np.ndarray:
    """A fala a 16 kHz, mono, cortada ou completada com silêncio até `duration`: o clipe tem o tempo do trecho, e
    não o do áudio, e os quadros saem na quantidade certa."""
    import librosa

    from .ditto_sdk import AUDIO_RATE

    audio, _ = librosa.load(str(path), sr=AUDIO_RATE, mono=True)
    wanted = round(duration * AUDIO_RATE)
    audio = audio[:wanted]
    if len(audio) < wanted:
        audio = np.concatenate([audio, np.zeros(wanted - len(audio), dtype=audio.dtype)])
    return audio.astype(np.float32)


def run(arguments: WorkerArguments, emit: EMIT) -> None:
    from .ditto_fast import HybridWarp, OpenVinoDecoder, detect_accelerator
    from .ditto_models import paths_in
    from .ditto_sdk import DittoSdk, seed_everything

    started = time.perf_counter()
    paths = paths_in(arguments.models_dir)
    arguments.frames_dir.mkdir(parents=True, exist_ok=True)
    arguments.cache_dir.mkdir(parents=True, exist_ok=True)
    seed_everything(arguments.seed)

    emit(format_event("ETAPA", "carregando os modelos"))
    accelerator = detect_accelerator()
    emit(format_event("DISPOSITIVO", f"OpenVINO em {accelerator.describe}"))
    warp = HybridWarp(
        paths, accelerator, arguments.cache_dir, log=lambda text: emit(format_event("AVISO", text))
    )
    decoder = OpenVinoDecoder(paths.onnx("decoder.onnx"), accelerator, arguments.cache_dir)
    emit(
        format_event(
            "ETAPA", "aquecendo o acelerador (na primeira vez compila os kernels da GPU, leva minutos)"
        )
    )
    warp.warm_up()
    decoder.warm_up()

    sdk = DittoSdk(paths, warp, decoder)
    emit(format_event("ETAPA", "achando o rosto e preparando a foto"))
    sdk.register_photo(arguments.photo, arguments.steps)

    emit(format_event("ETAPA", "ouvindo a fala"))
    features = sdk.audio_features(load_speech(arguments.audio, arguments.duration))
    total = len(features)
    generation_started = time.perf_counter()
    emit(format_event("ETAPA", f"desenhando {total} quadros"))

    def on_frame(index: int, frame: np.ndarray) -> None:
        path = arguments.frames_dir / f"{index:06d}.rgb"
        partial = path.with_suffix(".part")
        partial.write_bytes(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
        partial.replace(path)  # quem lê só vê o arquivo inteiro
        emit(format_event("QUADRO", index + 1, total, path))

    sdk.generate(features, on_frame)
    emit(format_event("PRONTO", total, f"{time.perf_counter() - generation_started:.1f}"))
    emit(format_event("ETAPA", f"preparo de {generation_started - started:.1f} s"))


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    def emit(line: str) -> None:
        print(line, flush=True)

    try:
        run(arguments, emit)
    except Exception as exc:  # noqa: BLE001 - quem chamou mostra a mensagem
        emit(format_event("ERRO", f"{type(exc).__name__}: {exc}".replace("\n", " ")))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

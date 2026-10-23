"""Registro dos modelos de IA que o DMaker baixa para `cache/models`: o que são, para que servem e onde ficam.

É dado puro: não toca disco nem rede. O inventário e as ações (baixar, apagar) estão em
`pipeline.models_service`. Um modelo novo entra com uma linha em `REGISTRY`; se ele usa um motor que já
tem função de download em `pipeline.model_fetchers`, nada mais muda.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

ModelState = Literal["installed", "partial", "absent"]

# Abaixo disso o modelo não está inteiro. 90% e não 100% porque o tamanho esperado é a medida de uma
# máquina e o Hugging Face acrescenta ou tira arquivos pequenos (README, refs) entre revisões.
INSTALLED_FRACTION = 0.9

# Entradas que o próprio Hugging Face cria na raiz de cache/models e que não pertencem a modelo nenhum.
RESERVED_ENTRIES = frozenset({".locks", "CACHEDIR.TAG"})

# Arquivos que um download em andamento deixa para trás; pertencem ao modelo que está sendo baixado.
INCOMPLETE_SUFFIXES = (".part", ".incomplete")


@dataclass(frozen=True)
class ModelSpec:
    """Um modelo baixável.

    `paths` são os caminhos (arquivos ou pastas) dentro de `cache/models` que só ele precisa; dois modelos
    podem dividir um caminho (o Kokoro fp32 e o int8 dividem o arquivo de vozes). `fetch` é
    `"modulo:funcao"` de uma função `(models_dir, variant) -> None` que baixa tudo o que falta: fica como
    texto para o registro não importar os motores (torch, onnx) só para listar.
    """

    id: str
    name: str
    purpose: str
    engine: str
    license: str
    paths: tuple[str, ...]
    expected_size: int
    required_by: tuple[str, ...]
    fetch: str
    variant: str = ""

    def __post_init__(self) -> None:
        if not self.paths:
            raise ValueError(f"O modelo {self.id!r} precisa de pelo menos um caminho.")
        for path in self.paths:
            if not is_safe_relative(path):
                raise ValueError(f"Caminho inseguro no modelo {self.id!r}: {path!r}")


def is_safe_relative(path: str) -> bool:
    """Caminho relativo, com barras normais, sem `..` nem raiz: não consegue sair de `cache/models`."""
    if not path or "\\" in path or ":" in path:
        return False
    # o texto cru e não `PurePosixPath.parts`, que já engole "." e "//" e esconderia o que se quer recusar
    segments = path.split("/")
    return not PurePosixPath(path).is_absolute() and all(s and s not in {".", ".."} for s in segments)


def classify(present: bool, size: int, expected: int, incomplete: bool) -> ModelState:
    """`installed` só com tamanho de modelo inteiro e sem resto de download; o que está pela metade é `partial`."""
    if not present:
        return "absent"
    if incomplete or size < expected * INSTALLED_FRACTION:
        return "partial"
    return "installed"


def format_size(size: int) -> str:
    """Tamanho como o Explorador do Windows mostra (base 1024), com vírgula decimal: `3,04 GB`, `80,1 MB`."""
    value = float(max(size, 0))
    for unit, decimals in (("B", 0), ("KB", 0), ("MB", 1), ("GB", 2)):
        if value < 1024 or unit == "GB":
            return f"{value:.{decimals}f} {unit}".replace(".", ",")
        value /= 1024
    raise AssertionError("inalcançável")  # pragma: no cover


# O tamanho small é o que o DMaker usa sozinho; os outros só entram quando o projeto ou o comando os pede.
WHISPER_DEFAULT_SIZE = "small"
_WHISPER_BY_DEFAULT = (
    "Legendas automáticas",
    "Transcrição de áudio",
    "Correção de fala",
    "Clonagem de voz (transcreve a referência)",
    "Dublagem",
    "Plano multicâmera",
)
_WHISPER_ON_REQUEST = ("Legendas e transcrição quando o projeto ou o comando pede este tamanho",)


def _whisper(size: str, expected: int, note: str) -> ModelSpec:
    return ModelSpec(
        id=f"whisper-{size}",
        name=f"Whisper {size} (faster-whisper)",
        purpose=f"Transcreve a fala em texto com tempo por palavra. {note}",
        engine="faster-whisper",
        license="MIT",
        paths=(f"models--Systran--faster-whisper-{size}",),
        expected_size=expected,
        required_by=_WHISPER_BY_DEFAULT if size == WHISPER_DEFAULT_SIZE else _WHISPER_ON_REQUEST,
        fetch="dmaker.pipeline.model_fetchers:fetch_whisper",
        variant=size,
    )


# Tamanhos esperados em bytes, medidos num download real (OmniVoice, Demucs, Whisper small, Kokoro, RVM). Os
# outros Whisper (tiny, base, medium, large-v3) são aproximados: servem para a estimativa e para
# reconhecer um download pela metade, e `INSTALLED_FRACTION` absorve a diferença.
REGISTRY: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="omnivoice",
        name="OmniVoice",
        purpose="Fala em mais de 600 idiomas, clona voz e cria voz por descrição (a voz padrão da narração).",
        engine="omnivoice",
        license="Apache-2.0",
        paths=("omnivoice",),
        expected_size=3_267_869_931,
        required_by=("Narração", "Clonagem de voz", "Voz por descrição", "Correção de fala", "Dublagem"),
        fetch="dmaker.pipeline.model_fetchers:fetch_omnivoice",
    ),
    ModelSpec(
        id="kokoro-fp32",
        name="Kokoro 82M (fp32)",
        purpose="Vozes prontas em português (dora, alex, santa), rápidas, para rascunho de narração.",
        engine="kokoro",
        license="Apache-2.0",
        paths=("kokoro/kokoro-v1.0.onnx", "kokoro/voices-v1.0.bin"),
        expected_size=325_532_387 + 28_214_398,
        required_by=("Narração com as vozes prontas (dora, alex, santa)",),
        fetch="dmaker.pipeline.model_fetchers:fetch_kokoro",
        variant="fp32",
    ),
    ModelSpec(
        id="kokoro-int8",
        name="Kokoro 82M (int8)",
        purpose="A mesma voz pronta do Kokoro em versão menor (92 MB), um pouco mais lenta nesta CPU.",
        engine="kokoro",
        license="Apache-2.0",
        paths=("kokoro/kokoro-v1.0.int8.onnx", "kokoro/voices-v1.0.bin"),
        expected_size=92_361_271 + 28_214_398,
        required_by=("Narração com as vozes prontas (dora, alex, santa) na variante int8",),
        fetch="dmaker.pipeline.model_fetchers:fetch_kokoro",
        variant="int8",
    ),
    ModelSpec(
        id="demucs-htdemucs",
        name="Demucs htdemucs",
        purpose="Separa a voz da música e do ruído de fundo (isolamento vocal).",
        engine="demucs",
        license="MIT",
        paths=("demucs",),
        expected_size=84_025_501,
        required_by=("Isolamento vocal", "Correção de fala", "Dublagem que mantém o fundo"),
        fetch="dmaker.pipeline.model_fetchers:fetch_demucs",
        variant="htdemucs",
    ),
    _whisper("tiny", 78_000_000, "O menor e mais rápido, com mais erros."),
    _whisper("base", 148_000_000, "Pequeno e rápido, com alguns erros."),
    _whisper("small", 486_213_279, "O padrão do DMaker."),
    _whisper("medium", 1_531_000_000, "Mais preciso e bem mais lento na CPU."),
    _whisper("large-v3", 3_093_000_000, "O mais preciso, muito lento na CPU."),
    ModelSpec(
        id="rvm-resnet50",
        name="Robust Video Matting (resnet50)",
        purpose="Recorta a pessoa do vídeo para trocar o fundo sem chroma key (o melhor recorte).",
        engine="rvm",
        license="GPL-3.0",
        paths=("rvm_resnet50_fp32.onnx",),
        expected_size=107_479_165,
        required_by=("Fundo trocado atrás da pessoa (matte)",),
        fetch="dmaker.pipeline.model_fetchers:fetch_matting",
        variant="resnet50",
    ),
    ModelSpec(
        id="rvm-mobilenetv3",
        name="Robust Video Matting (mobilenetv3)",
        purpose="O mesmo recorte de pessoa em versão leve, 2,5 vezes mais rápida e com borda menos fina.",
        engine="rvm",
        license="GPL-3.0",
        paths=("rvm_mobilenetv3_fp32.onnx",),
        expected_size=14_975_696,
        required_by=("Fundo trocado atrás da pessoa (matte) com o modelo mobilenetv3",),
        fetch="dmaker.pipeline.model_fetchers:fetch_matting",
        variant="mobilenetv3",
    ),
)


def find_model(model_id: str, specs: tuple[ModelSpec, ...] = REGISTRY) -> ModelSpec | None:
    return next((spec for spec in specs if spec.id == model_id), None)


def exclusive_paths(spec: ModelSpec, specs: tuple[ModelSpec, ...] = REGISTRY) -> tuple[str, ...]:
    """Caminhos que só este modelo reivindica. É por eles que se sabe se o modelo está lá: o arquivo de vozes
    do Kokoro, dividido, não faz o fp32 parecer instalado só porque o int8 está."""
    others = {path for other in specs if other.id != spec.id for path in other.paths}
    return tuple(path for path in spec.paths if path not in others) or spec.paths

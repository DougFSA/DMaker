"""O "site" que a composição em HTML enxerga: uma origem falsa que só serve arquivos locais.

A página é aberta em `http://dmaker.composicao/` e cada pedido dela é respondido daqui, do disco, sem rede: a
composição (um arquivo `.html` ou uma pasta com `index.html`), as bibliotecas do DMaker em `/_dmaker/` (three.js,
lottie-web, rough-notation, os emojis animados), a fonte da marca e os arquivos do projeto que a composição
declarou (`/_dmaker/files/`). Nada aqui abre navegador nem rede, então o que é servido e o que é negado se testa
sem Chromium. Uma origem falsa, e não `file://`, porque o `file://` bloqueia `fetch` de JSON local, módulos ES e o
Lottie.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .. import config

ORIGIN = "http://dmaker.composicao"
HOST = "dmaker.composicao"
ENTRY_PATH = "/index.html"
DMAKER_PREFIX = "/_dmaker/"
FONTS_PREFIX = DMAKER_PREFIX + "fonts/"
# arquivos de fora da pasta da composição que ela declarou (imagens do projeto, fontes da marca): o nome na URL
# é o que a composição pediu, nunca um caminho do disco
FILES_PREFIX = DMAKER_PREFIX + "files/"
HTML_SUFFIXES = (".html", ".htm")

# O `mimetypes` do Windows lê o registro da máquina e erra tipos de script e dados; os que a composição usa de
# verdade ficam fixos aqui, e o resto cai no que o sistema souber.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".wasm": "application/wasm",
    ".txt": "text/plain; charset=utf-8",
}

# Peso CSS de cada arquivo da Poppins em `assets/fonts` (a `@font-face` que o DMaker põe em toda composição).
POPPINS_FACES: tuple[tuple[str, int, str], ...] = (
    ("Poppins-Light.ttf", 300, "normal"),
    ("Poppins-Regular.ttf", 400, "normal"),
    ("Poppins-Medium.ttf", 500, "normal"),
    ("Poppins-SemiBold.ttf", 600, "normal"),
    ("Poppins-Bold.ttf", 700, "normal"),
    ("Poppins-ExtraBold.ttf", 800, "normal"),
    ("Poppins-Italic.ttf", 400, "italic"),
    ("Poppins-BoldItalic.ttf", 700, "italic"),
)


@dataclass(frozen=True)
class FontFace:
    """Um arquivo de fonte da marca que a página recebe por `@font-face`: a família CSS, o peso e o estilo."""

    family: str
    weight: int
    style: str
    path: Path


@dataclass(frozen=True)
class Served:
    """Um arquivo respondido à página."""

    body: bytes
    content_type: str


def content_type_of(path: Path | str) -> str:
    suffix = Path(path).suffix.lower()
    return CONTENT_TYPES.get(suffix) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def entry_file(source: Path) -> Path:
    """O `.html` da página: o próprio arquivo ou o `index.html` da pasta. Levanta o erro que diz o que falta."""
    if source.is_dir():
        entry = source / "index.html"
        if not entry.is_file():
            raise FileNotFoundError(f"A pasta da composição HTML não tem index.html: {source}")
        return entry
    if not source.exists():
        raise FileNotFoundError(f"Composição HTML não encontrada: {source}")
    if source.suffix.lower() not in HTML_SUFFIXES:
        raise ValueError(
            f"A composição HTML precisa ser um arquivo .html ou uma pasta com index.html: {source}"
        )
    return source


def composition_files(source: Path) -> list[Path]:
    """Os arquivos que a página pode usar, em ordem estável: só o `.html` (arquivo avulso) ou a pasta inteira.
    É o que entra na chave do cache."""
    entry = entry_file(source)
    if source.is_dir():
        return sorted(p for p in source.rglob("*") if p.is_file())
    return [entry]


def font_faces_css(fonts_dir: Path, family: str = "Poppins") -> str:
    """As `@font-face` da Poppins dos arquivos que existem em `assets/fonts` (a marca usa essa fonte)."""
    rules = []
    for filename, weight, style in POPPINS_FACES:
        if (fonts_dir / filename).is_file():
            rules.append(
                f'@font-face{{font-family:"{family}";font-weight:{weight};font-style:{style};'
                f"font-display:block;src:url({FONTS_PREFIX}{filename}) format('truetype')}}"
            )
    return "".join(rules)


def font_face_probes(fonts_dir: Path, family: str = "Poppins") -> list[str]:
    """Atalhos de fonte (`400 16px "Poppins"`) que a página manda carregar antes do primeiro quadro, para um peso
    que só aparece no meio da composição não surgir trocado."""
    return [
        f'{style if style != "normal" else ""} {weight} 16px "{family}"'.strip()
        for filename, weight, style in POPPINS_FACES
        if (fonts_dir / filename).is_file()
    ]


def font_file_names(faces: Sequence[FontFace]) -> dict[str, Path]:
    """O nome servido de cada fonte da marca (`font-0.ttf`...), na ordem recebida."""
    return {f"font-{index}{face.path.suffix.lower()}": face.path for index, face in enumerate(faces)}


def brand_font_faces_css(faces: Sequence[FontFace]) -> str:
    """As `@font-face` das fontes da marca que não estão em `assets/fonts` (a família do `brand.json` quando não é a
    Poppins e as fontes por papel de `fonts.files`), servidas pelo nome de `font_file_names`."""
    rules = []
    for name, face in zip(font_file_names(faces), faces, strict=True):
        rules.append(
            f'@font-face{{font-family:"{face.family}";font-weight:{face.weight};font-style:{face.style};'
            f"font-display:block;src:url({FILES_PREFIX}{name}) format('truetype')}}"
        )
    return "".join(rules)


def brand_font_probes(faces: Sequence[FontFace]) -> list[str]:
    """Os atalhos de fonte das fontes da marca, para a página mandá-las carregar antes do primeiro quadro."""
    return [
        f'{face.style if face.style != "normal" else ""} {face.weight} 16px "{face.family}"'.strip()
        for face in faces
    ]


def brand_css(
    colors: dict[str, str],
    family: str,
    radius: float | None = None,
    role_fonts: Mapping[str, str] | None = None,
) -> str:
    """As cores da marca como variáveis CSS (`--dm-primary`, `--dm-accent`...), a fonte dela em `--dm-font`, o raio
    dos cantos em `--dm-radius` (px na base 1080) e as fontes por papel em `--dm-font-<papel>`: a composição usa
    `var(--dm-accent)` e muda de marca sem mudar uma linha."""
    variables = [f"--dm-{name.replace('_', '-')}:{value}" for name, value in sorted(colors.items())]
    variables.append(f'--dm-font:"{family}",sans-serif')
    if radius is not None:
        variables.append(f"--dm-radius:{radius:g}px")
    for role, css_family in sorted((role_fonts or {}).items()):
        variables.append(f'--dm-font-{role}:"{css_family}","{family}",sans-serif')
    return ":root{" + ";".join(variables) + "}"


# Toda animação CSS nasce parada, para não andar em tempo real entre o carregamento da página e o primeiro quadro
# (quem a posiciona é o relógio da composição, em `html_runtime.js`).
FREEZE_CSS = "*,*::before,*::after{animation-play-state:paused !important}"


class CompositionSite:
    """Responde, do disco, ao que a página pede. `lookup` devolve None para o que não existe ou está fora do
    alcance dela (uma pasta acima, outro disco): quem pede recebe 404 e o aviso."""

    def __init__(
        self,
        source: Path,
        *,
        assets_dir: Path | None = None,
        fonts_dir: Path | None = None,
        files: Mapping[str, Path] | None = None,
    ):
        self.entry = entry_file(source)
        self.root = source.resolve() if source.is_dir() else None
        self.assets_dir = (assets_dir or config.HTML_ASSETS_DIR).resolve()
        self.fonts_dir = (fonts_dir or config.FONTS_DIR).resolve()
        self.files = {name: Path(path) for name, path in (files or {}).items()}

    def lookup(self, url_path: str) -> Served | None:
        path = unquote(url_path)
        if path in ("", "/", ENTRY_PATH):
            return self._file(self.entry)
        if path.startswith(FONTS_PREFIX):
            return self._inside(self.fonts_dir, path[len(FONTS_PREFIX) :])
        if path.startswith(FILES_PREFIX):
            declared = self.files.get(path[len(FILES_PREFIX) :])
            return self._file(declared) if declared is not None and declared.is_file() else None
        if path.startswith(DMAKER_PREFIX):
            return self._inside(self.assets_dir, path[len(DMAKER_PREFIX) :])
        if self.root is None:
            return None  # arquivo avulso: a página é só ele
        return self._inside(self.root, path.lstrip("/"))

    @staticmethod
    def _inside(base: Path, relative: str) -> Served | None:
        target = (base / relative).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            return None
        return CompositionSite._file(target)

    @staticmethod
    def _file(path: Path) -> Served:
        return Served(path.read_bytes(), content_type_of(path))


def is_composition_origin(url: str) -> bool:
    """A URL é da origem falsa (e portanto servida daqui); qualquer outra é pedido de rede e vai ser negada."""
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and parts.hostname == HOST


def is_local_scheme(url: str) -> bool:
    """`data:`, `blob:` e `about:` não saem da máquina: o navegador os resolve sozinho."""
    return urlsplit(url).scheme in ("data", "blob", "about")

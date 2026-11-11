"""O contêiner que monta o pacote do Linux: o script que roda dentro dele e os comandos `docker` que o chamam. Puro.

O contêiner é um `ubuntu:22.04` (a glibc mais antiga das duas de referência, então o pacote roda também no 24.04).
Todo o trabalho pesado fica numa pasta do X: montada por bind mount, não no disco virtual do WSL (que fica no C: e não
encolhe sozinho). A rede só é usada pelo pip e pelo Playwright; os arquivos grandes já chegam baixados e conferidos."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .naming import SLICE_BYTES, installer_basename
from .platforms import TORCH_CPU_INDEX

BUILD_IMAGE = "ubuntu:22.04"
# Os pacotes do apt que o build precisa no contêiner: certificados (o pip e o Playwright baixam por HTTPS), o `xz` do FFmpeg
# e o `zstd` do Ollama. Nada de compilador: todo pacote Python do DMaker tem wheel pronto para o Linux.
BUILD_APT_PACKAGES = ("ca-certificates", "xz-utils", "zstd")
# Pontos de montagem dentro do contêiner.
WORK = "/work"
DOWNLOADS = "/baixados"
MODELS = "/modelos"
OUTPUT = "/saida"


@dataclass(frozen=True)
class ContainerPlan:
    version: str
    python_archive: str
    ffmpeg_archive: str
    ollama_archive: str
    wheel_name: str
    extras: Sequence[str]
    model_paths: Sequence[str]  # relativos a cache/models, como o manifesto (só os de dados)
    slice_bytes: int = SLICE_BYTES

    @property
    def parts_prefix(self) -> str:
        return f"{OUTPUT}/{installer_basename(self.version, 'linux')}-"


def model_transform(model_paths: Sequence[str]) -> str:
    """A expressão do `tar --transform` que põe os modelos em `dados/cache/models/`, só no que está na lista (o resto
    do arquivo, `programa/`, não casa com nenhum caminho de modelo)."""
    escaped = [path.replace(".", "[.]") for path in sorted(model_paths)]
    alternatives = "|".join(escaped)
    # O `x` do final liga a expressão regular estendida (o `|` das alternativas); `&` é o trecho que casou.
    return "s," + "^(" + alternatives + "),dados/cache/models/&,x"


def build_script(plan: ContainerPlan) -> str:
    """O script de shell que o contêiner roda. Cada trecho diz o que faz em `echo`, que vira o log do build."""
    wheel = f"{WORK}/wheels/{plan.wheel_name}[{','.join(plan.extras)}]"
    return f"""#!/bin/sh
set -eu
# Todo pip e todo python daqui rodam isolados: nada do ambiente de quem monta entra no pacote.
export PYTHONNOUSERSITE=1 PYTHONPATH= PYTHONHOME= PIP_USER=0
export DEBIAN_FRONTEND=noninteractive
# O temporário do pip (a roda do torch tem centenas de MB) fica no X:, não no disco do contêiner.
export TMPDIR={WORK}/tmp
mkdir -p "$TMPDIR"
PROGRAMA={WORK}/programa
PY="$PROGRAMA/python/bin/python3"

echo "== apt: {" ".join(BUILD_APT_PACKAGES)}"
apt-get update -qq
apt-get install -y -qq --no-install-recommends {" ".join(BUILD_APT_PACKAGES)}

echo "== Python portátil"
tar -xzf "{DOWNLOADS}/{plan.python_archive}" -C "$PROGRAMA"

echo "== pip install"
"$PY" -m pip install --no-cache-dir --no-warn-script-location --disable-pip-version-check --no-input \\
    -c {WORK}/restricoes.txt --extra-index-url {TORCH_CPU_INDEX} "{wheel}" torch torchaudio

echo "== compileall"
"$PY" -m compileall -q -j 0 "$PROGRAMA/python" >/dev/null || true
# Os executáveis que o pip gera guardam o caminho do contêiner no shebang e quebram ao mudar de pasta.
for arquivo in "$PROGRAMA"/python/bin/*; do
    if [ -f "$arquivo" ] && [ ! -L "$arquivo" ] && head -n 1 "$arquivo" 2>/dev/null | grep -q '^#!{WORK}/'; then
        rm -f "$arquivo"
    fi
done

echo "== FFmpeg"
mkdir -p "$PROGRAMA/bin/ffmpeg"
tar -xJf "{DOWNLOADS}/{plan.ffmpeg_archive}" -C "$PROGRAMA/bin/ffmpeg" --strip-components=1
ln -sfn ffmpeg "$PROGRAMA/bin/ffmpeg-lv2"
"$PROGRAMA/bin/ffmpeg/bin/ffmpeg" -hide_banner -filters >{WORK}/filtros.txt
"$PROGRAMA/bin/ffmpeg/bin/ffmpeg" -hide_banner -version | head -n 1 >{WORK}/ffmpeg-versao.txt

echo "== Chromium (Playwright)"
PLAYWRIGHT_BROWSERS_PATH="$PROGRAMA/bin/playwright" "$PY" -m playwright install chromium
: >{WORK}/chromium-libs.txt
for binario in $(find "$PROGRAMA/bin/playwright" -type f \\( -name chrome -o -name headless_shell -o -name chrome-headless-shell \\)); do
    ldd "$binario" >>{WORK}/chromium-libs.txt 2>&1 || true
done

echo "== Ollama"
mkdir -p "$PROGRAMA/ollama"
zstd -dc "{DOWNLOADS}/{plan.ollama_archive}" | tar -x -C "$PROGRAMA/ollama"

echo "== permissões e tamanhos"
# Os arquivos que o Windows pôs na pasta aparecem executáveis no bind mount: só os binários e scripts devem ser.
find "$PROGRAMA/assets" "$PROGRAMA/templates" "$PROGRAMA/licencas" -type f -exec chmod 644 {{}} +
du -sb "$PROGRAMA" | cut -f1 >{WORK}/tamanho-programa.txt

echo "== partes (tar | gzip | split)"
rm -f {plan.parts_prefix}*.part
tar -cf - --owner=0 --group=0 --numeric-owner \\
    -C {WORK} programa \\
    -C {MODELS} -T {WORK}/modelos.txt --transform='{model_transform(plan.model_paths)}' \\
    | gzip -3 \\
    | split -b {plan.slice_bytes} -d -a 1 --numeric-suffixes=1 --additional-suffix=.part - {plan.parts_prefix}
echo "== pronto"
"""


def docker_run(
    docker: str,
    mounts: Sequence[tuple[Path, str, bool]],
    command: Sequence[str],
    image: str = BUILD_IMAGE,
) -> list[str]:
    """`docker run --rm` com os bind mounts `(pasta no Windows, ponto no contêiner, somente leitura)`."""
    args = [docker, "run", "--rm"]
    for folder, target, read_only in mounts:
        args += ["-v", f"{folder.as_posix()}:{target}" + (":ro" if read_only else "")]
    return [*args, image, *command]


def clean_command(docker: str, work: Path) -> list[str]:
    """Apaga, de dentro do contêiner, a árvore de trabalho anterior: os links e as permissões que o contêiner cria no
    bind mount o Windows nem sempre apaga."""
    folders = [
        "programa",
        "tmp",
        "filtros.txt",
        "ffmpeg-versao.txt",
        "chromium-libs.txt",
        "tamanho-programa.txt",
    ]
    targets = " ".join(f"{WORK}/{name}" for name in folders)
    return docker_run(docker, [(work, WORK, False)], ["sh", "-c", f"rm -rf {targets}"])

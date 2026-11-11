"""O alvo do Windows: Python portátil e pip rodando na própria máquina, e o Inno Setup (ISCC) faz o instalador."""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

from ..licenses import license_notice
from ..marker import marker_template, windows_launchers
from ..naming import SLICE_BYTES, installer_basename
from ..ollama import (
    OLLAMA_SUMS_NAME,
    OLLAMA_SUMS_URL,
    OLLAMA_VERSION,
    ollama_asset,
    ollama_local_name,
    ollama_url,
)
from ..platforms import TORCH_CPU_INDEX
from ..runner import ReleaseError
from ..staging import ISOLATED_ENV, longest_relative_path, wheel_requirement

if TYPE_CHECKING:
    from ..build import ReleaseBuilder, Step

INSTALLER_SCRIPT = Path("instalador") / "windows" / "dmaker.iss"
MARKER_TEMPLATE_NAME = "instalacao.json.modelo"
# O Windows recusa caminho com mais de 260 caracteres (MAX_PATH, contado com o NUL no fim): 259 de texto.
MAX_PATH_TEXT = 259


def max_install_folder(longest_relative: int) -> int:
    """O comprimento máximo da pasta de instalação para o caminho mais longo do pacote caber em 259 caracteres
    (a pasta, uma barra e o caminho relativo)."""
    return MAX_PATH_TEXT - 1 - longest_relative


class WindowsTarget:
    def work_dir(self, builder: ReleaseBuilder) -> Path:
        return builder.output / "_trabalho"

    def clear_previous(self, builder: ReleaseBuilder) -> None:
        for old in builder.output.glob(f"DMaker-{builder.options.version}-windows-*"):
            old.unlink()

    def steps(self, builder: ReleaseBuilder, wheel: Path) -> list[Step]:
        return [
            ("Python portátil", lambda: self.extract_python(builder)),
            ("pacotes Python (pip install)", lambda: self.install_packages(builder, wheel)),
            ("compileall", lambda: self.compile_python(builder)),
            ("copiar binários, assets e modelos", lambda: builder.stage_manifest(builder.manifest())),
            ("marcador, lançadores e licenças", lambda: self.write_support_files(builder)),
            ("instalador do Ollama", lambda: self.fetch_ollama(builder)),
            ("Inno Setup (ISCC)", lambda: self.run_installer_compiler(builder)),
        ]

    def python(self, builder: ReleaseBuilder) -> Path:
        return builder.program / builder.spec.python_exe

    def extract_python(self, builder: ReleaseBuilder) -> None:
        spec = builder.spec
        expected = builder.published_sum(spec.sums_url, f"SHA256SUMS-python-{spec.id}", spec.python_archive)
        if not expected:
            raise ReleaseError(f"O SHA256SUMS da release não lista {spec.python_archive}")
        archive = builder.fetch_verified(spec.python_url, spec.python_archive, expected)
        shutil.rmtree(builder.program, ignore_errors=True)
        builder.program.mkdir(parents=True)
        with tarfile.open(archive) as bundle:
            bundle.extractall(builder.program, filter="data")

    def install_packages(self, builder: ReleaseBuilder, wheel: Path) -> None:
        constraints = builder.host_constraints()
        builder.runner.run(
            [
                str(self.python(builder)),
                "-m",
                "pip",
                "install",
                "--no-warn-script-location",
                "--disable-pip-version-check",
                "--no-input",
                "-c",
                str(constraints),
                "--extra-index-url",
                TORCH_CPU_INDEX,
                wheel_requirement(wheel),
                "torch",
                "torchaudio",
            ],
            env=ISOLATED_ENV,
        )

    def compile_python(self, builder: ReleaseBuilder) -> None:
        # arquivo de terceiros com erro de sintaxe (ex.: de exemplo, em Python 2) faz o compileall sair com 1: não é falha
        builder.runner.run(
            [str(self.python(builder)), "-m", "compileall", "-q", "-j", "0", str(builder.program / "python")],
            env=ISOLATED_ENV,
            check=False,
            quiet=True,
        )
        # os executáveis que o pip gera guardam o caminho absoluto do Python e quebram ao mudar de pasta
        shutil.rmtree(builder.program / builder.spec.launcher_scripts, ignore_errors=True)

    def write_support_files(self, builder: ReleaseBuilder) -> None:
        options = builder.options
        (builder.program / MARKER_TEMPLATE_NAME).write_text(
            marker_template(options.version), encoding="utf-8"
        )
        for name, content in windows_launchers().items():
            (builder.program / name).write_bytes(content.encode("utf-8"))
        licenses = builder.program / "licencas"
        licenses.mkdir(exist_ok=True)
        (licenses / "LICENCAS.txt").write_text(
            license_notice(options.version, "windows", options.excluded_models), encoding="utf-8-sig"
        )
        third_party = options.repo_root / "THIRD_PARTY.md"
        if third_party.exists():
            shutil.copy2(third_party, licenses / "THIRD_PARTY.md")

    def fetch_ollama(self, builder: ReleaseBuilder) -> Path:
        expected = builder.published_sum(OLLAMA_SUMS_URL, OLLAMA_SUMS_NAME, ollama_asset("windows"))
        return builder.fetch_verified(ollama_url("windows"), ollama_local_name("windows"), expected)

    def run_installer_compiler(self, builder: ReleaseBuilder) -> None:
        options = builder.options
        ollama = builder.downloads / ollama_local_name("windows")
        iscc = options.iscc or options.main_root / "bin" / "innosetup" / "ISCC.exe"
        # O limite de 260 caracteres: o ISCC leva o tamanho máximo da pasta, e o instalador recusa uma mais longa.
        max_program = max_install_folder(longest_relative_path(builder.program))
        max_data = max_install_folder(longest_relative_path(builder.models))
        builder.runner.run(
            [
                str(iscc),
                "/Qp",
                f"/DVersao={options.version}",
                f"/DPrograma={builder.program}",
                f"/DDados={builder.models}",
                f"/DSaida={builder.output}",
                f"/DNomeBase={installer_basename(options.version, builder.spec.id)}",
                f"/DOllama={ollama}",
                f"/DOllamaVersao={OLLAMA_VERSION}",
                f"/DFatia={SLICE_BYTES}",
                f"/DMaxPrograma={max_program}",
                f"/DMaxDados={max_data}",
                str(options.repo_root / INSTALLER_SCRIPT),
            ]
        )

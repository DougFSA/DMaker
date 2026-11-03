"""Empacotamento: leva o manual (docs/MANUAL.md e docs/ia) para dentro do pacote instalado.

Toda a configuração está no pyproject.toml; este arquivo existe só para uma coisa. O `package-data` do setuptools
não alcança pastas fora de `src/dmaker`, e a busca no manual (`search_manual`, `dmaker ajuda`) e os arquivos de
`docs/ia` precisam existir numa instalação comum, sem o repositório e sem internet. Então o `build_py` copia essas
pastas para `dmaker/resources/manual` na hora de montar o pacote.
"""

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent


class BuildPyWithManual(build_py):
    def run(self):
        super().run()
        docs = ROOT / "docs"
        if not (docs / "MANUAL.md").exists():
            return
        target = Path(self.build_lib) / "dmaker" / "resources" / "manual"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(docs / "MANUAL.md", target / "MANUAL.md")
        if (docs / "ia").exists():
            shutil.copytree(docs / "ia", target / "ia", dirs_exist_ok=True)


setup(cmdclass={"build_py": BuildPyWithManual})

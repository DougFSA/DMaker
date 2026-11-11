"""`dmaker release publish`: sobe os instaladores de uma versão para a aba Releases do GitHub, pelo `gh`.

Só publica depois do release (a tag `vX` já existe no `origin`) e pode ser repetido: uma queda no meio de 16 GB de
upload não obriga a recomeçar, porque o que já subiu inteiro fica e só o que falta é enviado. Todo comando externo passa
pelo `CommandRunner` injetado, então o teste prova a ordem sem tocar o GitHub."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__
from .checksums import parse_sha256sums, sha256_file
from .naming import GITHUB_FILE_LIMIT, release_folder_name
from .runner import CommandRunner, ReleaseError

SUMS_NAME = "SHA256SUMS.txt"
NOTES_NAME = "NOTAS.md"
_VERSION = re.compile(r"^v?(\d+)(?:\.0\.0)?$")


def parse_release_version(text: str) -> tuple[str, str]:
    """De `2`, `v2`, `2.0.0` ou `v2.0.0`, a tag (`v2`) e a versão do pacote (`2.0.0`): o nome da versão no Jira é o da tag."""
    match = _VERSION.match(text.strip())
    if not match:
        raise ReleaseError(f"Versão inválida: {text!r}. Use o nome da versão, como 2 (ou 2.0.0).")
    major = match.group(1)
    return f"v{major}", f"{major}.0.0"


@dataclass(frozen=True)
class PublishOptions:
    version: str  # como a pessoa digitou
    main_root: Path  # a pasta principal: `releases/v<versão>` fica nela
    repo_root: Path  # o clone de onde o `gh` descobre o repositório
    package_version: str = __version__  # a versão do código que está rodando


@dataclass
class PublishResult:
    tag: str
    url: str
    uploaded: list[str] = field(default_factory=list)
    already_there: list[str] = field(default_factory=list)
    created: bool = False


class ReleasePublisher:
    def __init__(
        self, options: PublishOptions, runner: CommandRunner, log: Callable[[str], None] = print
    ) -> None:
        self.options = options
        self.runner = runner
        self.log = log
        self.tag, self.package_version = parse_release_version(options.version)
        self.folder = options.main_root / "releases" / release_folder_name(self.package_version)

    # ---- as conferências (nada é enviado antes de todas passarem) ----

    def check_tag(self) -> None:
        listing = self.runner.run(
            ["git", "ls-remote", "--tags", "origin", f"refs/tags/{self.tag}"],
            cwd=self.options.repo_root,
            quiet=True,
        )
        if not listing.strip():
            raise ReleaseError(
                f"A tag {self.tag} não existe no origin. A publicação vem depois do release: crie a tag pela skill "
                "dmaker-producao e rode de novo."
            )

    def check_package_version(self) -> None:
        if self.options.package_version != self.package_version:
            raise ReleaseError(
                f"A versão do pacote ({self.options.package_version}) não bate com a tag {self.tag} "
                f"({self.package_version}). Rode o comando de um checkout da tag."
            )

    def check_files(self) -> list[Path]:
        """Os arquivos da release, na ordem do SHA256SUMS.txt, conferidos em existência, tamanho e hash."""
        sums_path = self.folder / SUMS_NAME
        if not sums_path.exists() or not (self.folder / NOTES_NAME).exists():
            raise ReleaseError(
                f"Faltam {SUMS_NAME} ou {NOTES_NAME} em {self.folder}: gere o instalador com `dmaker release build`."
            )
        listed = parse_sha256sums(sums_path.read_text(encoding="utf-8"))
        if not listed:
            raise ReleaseError(f"{SUMS_NAME} está vazio.")
        present = {path.name for path in self.folder.glob("DMaker-*")}
        extra = sorted(present - set(listed))
        if extra:
            raise ReleaseError(
                f"Arquivos na pasta que o {SUMS_NAME} não lista (build velho?): {', '.join(extra)}"
            )
        files = []
        for name, expected in listed.items():
            path = self.folder / name
            if not path.exists():
                raise ReleaseError(f"O {SUMS_NAME} lista {name}, que não está em {self.folder}.")
            if path.stat().st_size >= GITHUB_FILE_LIMIT:
                raise ReleaseError(f"{name} passa de 2 GiB, o limite de um arquivo de release do GitHub.")
            self.log(f"  conferindo o SHA-256 de {name}")
            if sha256_file(path) != expected:
                raise ReleaseError(
                    f"O SHA-256 de {name} não bate com o {SUMS_NAME}: o arquivo mudou depois do build."
                )
            files.append(path)
        return [*files, sums_path]

    # ---- o GitHub ----

    def gh(self, *args: str, quiet: bool = False) -> str:
        return self.runner.run(["gh", *args], cwd=self.options.repo_root, quiet=quiet)

    def release_exists(self) -> bool:
        listing = json.loads(
            self.gh("release", "list", "--limit", "200", "--json", "tagName", quiet=True) or "[]"
        )
        return any(item.get("tagName") == self.tag for item in listing)

    def release_assets(self) -> list[dict]:
        data = json.loads(self.gh("release", "view", self.tag, "--json", "assets", quiet=True) or "{}")
        return list(data.get("assets", []))

    def release_url(self) -> str:
        data = json.loads(self.gh("release", "view", self.tag, "--json", "url", quiet=True) or "{}")
        return str(data.get("url", ""))

    def publish(self) -> PublishResult:
        self.check_tag()
        self.check_package_version()
        files = self.check_files()
        title = f"DMaker {self.tag.removeprefix('v')}"
        notes = str(self.folder / NOTES_NAME)
        result = PublishResult(self.tag, "")
        if not self.release_exists():
            self.log(f"criando a release {self.tag} com {len(files)} arquivos")
            self.gh(
                "release",
                "create",
                self.tag,
                "--title",
                title,
                "--notes-file",
                notes,
                "--verify-tag",
                *map(str, files),
            )
            result.created = True
            result.uploaded = [path.name for path in files]
        else:
            assets = self.release_assets()
            # Um arquivo que a queda deixou pela metade (estado diferente de `uploaded`) não conta: sai e sobe de novo.
            there = {a["name"]: int(a["size"]) for a in assets if a.get("state") == "uploaded"}
            for asset in assets:
                if asset.get("state") != "uploaded":
                    self.log(f"  apagando o envio pela metade de {asset['name']}")
                    self.gh("release", "delete-asset", self.tag, asset["name"], "--yes")
            for path in files:
                if there.get(path.name) == path.stat().st_size:
                    result.already_there.append(path.name)
                    continue
                self.log(f"  enviando {path.name}")
                self.gh("release", "upload", self.tag, str(path), "--clobber")
                result.uploaded.append(path.name)
            self.gh("release", "edit", self.tag, "--title", title, "--notes-file", notes)
        result.url = self.release_url()
        return result

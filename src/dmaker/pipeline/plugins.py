"""Os plugins instalados: a varredura em cache, o habilitar e desabilitar, e a resolução de um plugin da spec para o que o
render precisa (o ffmpeg que o hospeda, a pasta de trabalho e o ambiente).

Os caminhos (`config.PLUGINS_FILE`, `config.PLUGIN_SCAN_DIR`) são lidos na hora do uso. A sondagem, as pastas e o ffmpeg de cada
formato entram por injeção; sem eles o serviço usa os de verdade.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from .. import config
from ..domain.plugins import PLUGIN_FORMATS, PluginInfo, PluginPorts
from ..media.plugin_host import PluginProbe, SubprocessProbe, host_ffmpeg
from ..media.plugin_scan import (
    NEEDS_LADSPA_HOST,
    NEEDS_LV2_HOST,
    PluginRoot,
    ScanResult,
    default_roots,
    scan_plugins,
)

SCAN_FILE_VERSION = 1


class PluginUnavailable(Exception):
    """O plugin que a spec cita não pode rodar aqui; a mensagem diz o motivo (não achado, desabilitado, sem o ffmpeg dele)."""


@dataclass(frozen=True)
class ResolvedPlugin:
    """O plugin da spec resolvido para o render: o que a varredura sabe dele e como rodar o ffmpeg que o hospeda."""

    info: PluginInfo
    ffmpeg: Path
    cwd: Path | None
    env: dict[str, str]

    @property
    def ports(self) -> PluginPorts:
        return self.info.ports

    def signature(self) -> list:
        """O que muda o som deste plugin além dos valores: o arquivo dele e o ffmpeg que o roda (data e tamanho de cada um).
        Entra na chave de cache do item, para atualizar o plugin refazer o arquivo processado."""
        return [
            self.info.format,
            self.info.ref,
            _stamp(Path(self.info.binary)),
            str(self.ffmpeg),
            _stamp(self.ffmpeg),
        ]


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        status = path.stat()
    except OSError:
        return None
    return status.st_mtime_ns, status.st_size


class PluginService:
    """Varre, lista, habilita e resolve plugins."""

    def __init__(
        self,
        probe: PluginProbe | None = None,
        roots: Callable[[], Iterable[PluginRoot]] | None = None,
        ffmpeg_for: Callable[[str], Path | None] | None = None,
    ) -> None:
        self._probe: PluginProbe = probe or SubprocessProbe()
        self._roots = roots or default_roots
        self._ffmpeg_for = ffmpeg_for or host_ffmpeg
        self._rescanned = False

    # ---------- varredura ----------

    @property
    def _scan_file(self) -> Path:
        return config.PLUGIN_SCAN_DIR / "scan.json"

    def scan(self) -> ScanResult:
        """Varre as pastas de novo e guarda o resultado. É o que `dmaker audio plugins scan` faz."""
        result = scan_plugins(self._roots(), self._probe, self._ffmpeg_for)
        self._scan_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCAN_FILE_VERSION,
            "plugins": [info.to_dict() for info in result.plugins],
            "notes": result.notes,
        }
        self._scan_file.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        self._rescanned = True
        return result

    def _cached(self) -> ScanResult | None:
        try:
            data = json.loads(self._scan_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("version") != SCAN_FILE_VERSION:
            return None
        return ScanResult(
            [PluginInfo.from_dict(item) for item in data["plugins"]], list(data.get("notes", []))
        )

    def result(self) -> ScanResult:
        """O resultado da última varredura (faz uma se nunca houve), com o habilitar de cada plugin aplicado."""
        scanned = self._cached() or self.scan()
        off = self._disabled()
        plugins = [
            replace(info, enabled=_state_key(info.format, info.ref) not in off) for info in scanned.plugins
        ]
        return ScanResult(plugins, scanned.notes)

    def plugins(self) -> list[PluginInfo]:
        return self.result().plugins

    def find(self, key: str, format_name: str | None = None) -> PluginInfo | None:
        """Um plugin pelo `id` curto (`lv2-1a2b3c4d5e`) ou pela referência da spec (a URI, `arquivo#rótulo`)."""
        for info in self.plugins():
            if (info.id == key or info.ref == key) and (format_name is None or info.format == format_name):
                return info
        return None

    def hosts(self) -> dict[str, str | None]:
        """O ffmpeg que hospeda cada formato, ou None quando nenhum tem o filtro (é o que `dmaker doctor` mostra)."""
        return {name: str(found) if (found := self._ffmpeg_for(name)) else None for name in PLUGIN_FORMATS}

    def catalog(self, key: str | None = None) -> dict:
        """A lista dos plugins como a API, o MCP e a CLI a entregam: cada plugin com os controles, as pastas varridas, os
        ffmpeg que hospedam cada formato e o que a varredura não conseguiu ler. Com `key`, só aquele plugin."""
        result = self.result()
        plugins = result.plugins
        if key is not None:
            found = self.find(key)
            if found is None:
                raise PluginUnavailable(
                    f"plugin {key!r} não encontrado (veja `dmaker audio plugins list`; depois de instalar, `dmaker audio plugins scan`)"
                )
            plugins = [found]
        return {
            "plugins": [info.to_dict() for info in plugins],
            "notes": result.notes,
            "hosts": self.hosts(),
            "folders": [
                {"format": root.format, "path": str(root.path), "exists": root.path.is_dir()}
                for root in self._roots()
            ],
            "install_to": str(config.PLUGINS_DIR),
        }

    # ---------- habilitar e desabilitar ----------

    def _disabled(self) -> set[str]:
        try:
            data = json.loads(config.PLUGINS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return {str(item) for item in data.get("disabled", [])}

    def set_enabled(self, key: str, enabled: bool) -> PluginInfo:
        """Liga ou desliga um plugin (o desligado fica na lista, mas os efeitos que o usam são pulados com um aviso)."""
        info = self.find(key)
        if info is None:
            raise PluginUnavailable(
                f"plugin {key!r} não encontrado (veja `dmaker audio plugins list`; depois de instalar, `dmaker audio plugins scan`)"
            )
        off = self._disabled()
        marker = _state_key(info.format, info.ref)
        if enabled:
            off.discard(marker)
        else:
            off.add(marker)
        config.PLUGINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.PLUGINS_FILE.write_text(
            json.dumps({"disabled": sorted(off)}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return replace(info, enabled=enabled)

    # ---------- resolver para o render ----------

    def problem(self, format_name: str, ref: str) -> str | None:
        """Por que o plugin da spec não pode rodar aqui, ou None quando pode."""
        try:
            self.resolve(format_name, ref)
        except PluginUnavailable as exc:
            return str(exc)
        return None

    def resolve(self, format_name: str, ref: str) -> ResolvedPlugin:
        """O plugin pronto para rodar, ou `PluginUnavailable` com o motivo. Se a varredura guardada não o conhece, varre de novo
        uma vez (a pessoa pode tê-lo instalado depois)."""
        info = self.find(ref, format_name)
        if (info is None or not Path(info.binary).exists()) and not self._rescanned:
            self.scan()
            info = self.find(ref, format_name)
        if info is None or not Path(info.binary or info.path).exists():
            raise PluginUnavailable(
                f"o plugin {ref!r} ({format_name.upper()}) não está instalado nesta máquina "
                "(depois de instalá-lo, `dmaker audio plugins scan`)"
            )
        if not info.enabled:
            raise PluginUnavailable(
                f"o plugin {info.name!r} está desabilitado (`dmaker audio plugins enable {info.id}`)"
            )
        ffmpeg = self._ffmpeg_for(format_name)
        if ffmpeg is None:
            raise PluginUnavailable(
                f"o plugin {info.name!r} precisa de um ffmpeg com o filtro {format_name}: "
                + (NEEDS_LV2_HOST if format_name == "lv2" else NEEDS_LADSPA_HOST)
            )
        if not info.usable:
            raise PluginUnavailable(f"o plugin {info.name!r} não pode ser usado: {info.problem}")
        if format_name == "lv2":
            return ResolvedPlugin(info, ffmpeg, None, {"LV2_PATH": str(Path(info.path).parent)})
        return ResolvedPlugin(info, ffmpeg, Path(info.path).parent, {})


def _state_key(format_name: str, ref: str) -> str:
    return f"{format_name}:{ref}"


_default: PluginService | None = None


def plugin_service() -> PluginService:
    """O serviço do processo, com a sondagem e as pastas de verdade."""
    global _default
    if _default is None:
        _default = PluginService()
    return _default

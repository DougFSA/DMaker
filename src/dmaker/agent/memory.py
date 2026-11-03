"""Memória do computador e a conta de quanto um modelo cabe nela.

A leitura da memória é um protocolo (`MemoryProbe`), com a implementação do Windows e `None` quando não se sabe:
a conta (`memory_fit`) é função pura, então se testa sem depender da máquina que roda o teste. Modelo grande demais
para a RAM não quebra nada, mas a resposta leva uma eternidade (a máquina troca memória com o disco); o aviso existe
para a pessoa saber antes de escolher.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Literal, Protocol

GIB = 1024**3
# Menos folga que isso e o sistema e os outros programas disputam a memória com o modelo: ele roda, mas devagar.
TIGHT_MARGIN_BYTES = int(1.5 * GIB)

# fits: cabe com folga · tight: cabe, mas apertado · too_big: maior que a RAM inteira · unknown: não deu para medir
Fit = Literal["fits", "tight", "too_big", "unknown"]


@dataclass(frozen=True)
class MemoryStatus:
    total: int  # bytes de RAM física
    available: int  # bytes de RAM física livres agora (inclui o cache que o sistema devolve sob demanda)

    def to_dict(self) -> dict[str, int]:
        return {"total": self.total, "available": self.available}


class MemoryProbe(Protocol):
    def read(self) -> MemoryStatus | None:
        """A memória agora, ou `None` se esta máquina não sabe dizer."""
        ...


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class WindowsMemoryProbe:
    """`GlobalMemoryStatusEx` do Windows, direto pelo ctypes: sem dependência nova para ler duas contas."""

    def read(self) -> MemoryStatus | None:
        if sys.platform != "win32":
            return None
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        try:
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return None
        except (AttributeError, OSError):
            return None
        return MemoryStatus(total=int(status.ullTotalPhys), available=int(status.ullAvailPhys))


def memory_fit(size: int | None, memory: MemoryStatus | None, loaded: bool = False) -> Fit:
    """Se um modelo de `size` bytes cabe na memória: cabe, apertado ou não cabe.

    Um modelo já carregado conta como "cabe": ele está rodando, e a memória que ele ocupa já saiu do "livre". "Não
    cabe" é só o modelo maior que a RAM inteira, que nenhuma folga resolve; abaixo disso a memória livre varia a cada
    minuto (navegador aberto, outro render), então falta de folga é "apertado", que avisa sem condenar um modelo que
    a máquina costuma rodar. Sem o tamanho ou sem a leitura da memória, "desconhecido".
    """
    if loaded:
        return "fits"
    if size is None or memory is None:
        return "unknown"
    if size > memory.total:
        return "too_big"
    if memory.available - size < TIGHT_MARGIN_BYTES:
        return "tight"
    return "fits"

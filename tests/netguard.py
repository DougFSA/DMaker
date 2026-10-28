"""Bloqueio de rede para testes: só conexões para a própria máquina (localhost) passam.

A bateria de perguntas ao manual precisa provar que roda sem internet. Dentro de `only_localhost()` qualquer tentativa
de falar com outro endereço falha na hora (e fica registrada em `blocked`), então um teste que dependesse da rede
reprovaria em vez de passar por sorte.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager

LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain"})


class NetworkBlocked(OSError):
    """Tentativa de conexão com um endereço que não é a própria máquina."""


def is_local(host: str | bytes | None) -> bool:
    """`127.0.0.0/8`, `::1` e `localhost` contam como a própria máquina."""
    if host is None:
        return True
    name = host.decode() if isinstance(host, bytes) else str(host)
    if name.lower() in LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(name.strip("[]")).is_loopback
    except ValueError:
        return False


@contextmanager
def only_localhost() -> Iterator[list[str]]:
    """Troca `connect` e a resolução de nomes por versões que recusam o que não é local; devolve a lista de recusas."""
    blocked: list[str] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def check(address: object) -> None:
        host = address[0] if isinstance(address, tuple) and address else None
        if isinstance(address, tuple) and not is_local(host):
            blocked.append(str(host))
            raise NetworkBlocked(f"rede bloqueada no teste: {host}")

    def connect(self, address):
        check(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        check(address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not is_local(host):
            blocked.append(str(host))
            raise NetworkBlocked(f"rede bloqueada no teste (DNS): {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    try:
        yield blocked
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = real_getaddrinfo  # type: ignore[assignment]

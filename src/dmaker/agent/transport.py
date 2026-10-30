"""Transporte HTTP do agente: requisição JSON, fluxo linha a linha e o Parar que fecha a conexão aberta.

Só stdlib (`urllib` e `http.client`), no padrão dos clientes de modelo: `opener` injetável para testar sem servidor
de verdade. O fluxo existe porque a resposta de um modelo local em CPU leva minutos: ler tudo de uma vez deixa a
tela muda e não dá como parar. Parar, aqui, é fechar o socket: o servidor percebe a conexão cair e para de gerar.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import urllib.request
from collections.abc import Callable
from typing import Any, Literal

# O que um trecho de fluxo é: pedaço da resposta ou pedaço do raciocínio do modelo (sempre texto não vazio).
DeltaKind = Literal["answer", "thinking"]
OnDelta = Callable[[DeltaKind, str], None]
# Consultado a cada trecho que chega; quem pede Parar marca o seu sinal ANTES de chamar `abort()` do cliente.
ShouldStop = Callable[[], bool]


class ChatStreamError(RuntimeError):
    """O servidor do modelo mandou um erro no meio do fluxo, ou a resposta veio ilegível ou cortada."""


def build_request(
    base_url: str, method: str, path: str, body: dict | None, headers: dict[str, str] | None = None
) -> urllib.request.Request:
    """Monta a requisição JSON; sem corpo (GET) não há `Content-Type`."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    merged = dict(headers or {})
    if data is not None:
        merged["Content-Type"] = "application/json"
    return urllib.request.Request(f"{base_url.rstrip('/')}{path}", data=data, method=method, headers=merged)


def request_json(
    opener: Callable[..., Any],
    base_url: str,
    method: str,
    path: str,
    body: dict | None,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> dict:
    """Uma chamada que devolve um JSON inteiro (tudo menos o fluxo)."""
    request = build_request(base_url, method, path, body, headers)
    with opener(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class StreamGuard:
    """Guarda o que fechar para que OUTRO thread interrompa a leitura em curso (o botão Parar).

    A conexão de um fluxo fica parada, sem trecho nenhum, enquanto o modelo carrega ou lê o pedido (minutos em CPU):
    é nessa espera que o Parar mais importa, e é nela que não existe resposta para fechar. Por isso o guarda
    recebe também o socket, assim que a conexão abre, e o desliga (`shutdown`), o que acorda a leitura bloqueada.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._closers: list[Callable[[], None]] = []
        self._aborted = False

    def begin(self) -> None:
        """Começa um fluxo novo: um Parar de um fluxo anterior não pode valer para este."""
        with self._lock:
            self._closers = []
            self._aborted = False

    def end(self) -> None:
        with self._lock:
            self._closers = []

    @property
    def aborted(self) -> bool:
        with self._lock:
            return self._aborted

    def register(self, closer: Callable[[], None]) -> bool:
        """Anota algo a fechar no Parar; se o Parar já veio, fecha agora e devolve `False`."""
        with self._lock:
            if not self._aborted:
                self._closers.append(closer)
                return True
        _quietly(closer)
        return False

    def abort(self) -> None:
        """Interrompe a leitura em curso. Seguro de qualquer thread, e inofensivo se nada está aberto."""
        with self._lock:
            self._aborted = True
            closers = list(self._closers)
        for closer in closers:  # na ordem do registro: o socket primeiro, que é o que acorda a leitura
            _quietly(closer)


def _quietly(closer: Callable[[], None]) -> None:
    try:
        closer()
    except Exception:  # noqa: BLE001 - fechar o que já caiu não pode virar erro de quem pediu Parar
        pass


def _shutdown(sock: socket.socket) -> None:
    """Desliga o socket sem fechá-lo: acorda o `recv` bloqueado de outro thread, que fecha no seu `with`."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


class _GuardedConnection:
    """Mistura para `HTTPConnection` e `HTTPSConnection`: entrega o socket ao guarda assim que a conexão abre."""

    def __init__(self, *args: Any, guard: StreamGuard, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._guard = guard

    def connect(self) -> None:
        super().connect()  # type: ignore[misc]  # a classe irmã na herança é a conexão http(s)
        sock = self.sock  # type: ignore[attr-defined]
        if not self._guard.register(lambda: _shutdown(sock)):
            raise OSError("A conexão foi interrompida antes de abrir.")


class _GuardedHTTPConnection(_GuardedConnection, http.client.HTTPConnection):
    pass


class _GuardedHTTPSConnection(_GuardedConnection, http.client.HTTPSConnection):
    pass


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, guard: StreamGuard) -> None:
        super().__init__()
        self._guard = guard

    def http_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_GuardedHTTPConnection, req, guard=self._guard)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, guard: StreamGuard) -> None:
        super().__init__()
        self._guard = guard

    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_GuardedHTTPSConnection, req, guard=self._guard)


def guarded_opener(guard: StreamGuard) -> Callable[..., Any]:
    """Um `urlopen` cujas conexões o `guard` conhece desde o `connect`, até antes de chegarem os cabeçalhos."""
    return urllib.request.build_opener(_GuardedHTTPHandler(guard), _GuardedHTTPSHandler(guard)).open


def read_stream(
    opener: Callable[..., Any],
    request: urllib.request.Request,
    timeout: float,
    guard: StreamGuard,
    feed: Callable[[str], bool],
    should_stop: ShouldStop | None = None,
) -> bool:
    """Lê a resposta linha a linha, passando cada linha não vazia a `feed`; devolve `True` se foi interrompida.

    `feed` devolve `True` quando a linha era a última da resposta. Terminar sem isso, sem Parar, é erro: a conexão
    caiu no meio. O `timeout` do `urlopen` vale por leitura (cada espera por dados), e não pela resposta inteira, então
    um modelo lento que ainda manda trechos não estoura. Toda saída, inclusive o Parar, fecha a conexão.
    """

    def stopped() -> bool:
        return guard.aborted or (should_stop is not None and should_stop())

    guard.begin()
    try:
        if stopped():
            return True
        try:
            with opener(request, timeout=timeout) as response:
                # com um opener injetado o guarda não conhece o socket: o Parar fecha a própria resposta
                guard.register(response.close)
                if stopped():
                    return True
                for raw in response:
                    text = raw.decode("utf-8", errors="replace").strip()
                    if text and feed(text):
                        return False
                    if stopped():
                        return True
        except (OSError, ValueError, http.client.HTTPException):
            if stopped():  # fechar o socket de outro thread derruba a leitura: é o Parar, não uma falha
                return True
            raise
        if stopped():
            return True
        raise ChatStreamError("A conexão com o modelo terminou antes do fim da resposta.")
    finally:
        guard.end()

"""Roteador de motores: escolhe quem fala pela voz do pedido (pronta -> Kokoro, o resto -> OmniVoice)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping

from ..config import DEFAULT_VOICE_ID
from .library import VoiceLibrary, VoiceProfile
from .synth import Speech, SpeechSynthesizer, VoiceRequest


class RoutingSynthesizer:
    """Implementa `SpeechSynthesizer` despachando cada pedido para o motor da voz.

    Sem voz no pedido fala o OmniVoice (voz automática ou, com `instruct`, voz desenhada), a menos que haja
    uma voz padrão configurada (`DMAKER_DEFAULT_VOICE`, ex.: a `dora` do Kokoro para rascunhos).
    """

    engine_id = "routing"

    def __init__(
        self,
        engines: Mapping[str, SpeechSynthesizer],
        default_voice_id: str | None = None,
        library_factory: Callable[[], VoiceLibrary] = VoiceLibrary,
    ) -> None:
        self.engines = dict(engines)
        self.default_voice_id = default_voice_id or DEFAULT_VOICE_ID  # None: OmniVoice com voz automática
        self._library_factory = library_factory

    def _default_voice(self) -> VoiceProfile | None:
        return self._library_factory().get(self.default_voice_id) if self.default_voice_id else None

    def _target(self, request: VoiceRequest) -> tuple[SpeechSynthesizer, VoiceRequest]:
        """Motor que atende o pedido e o pedido já com a voz padrão resolvida, se faltava voz."""
        voice = request.voice
        if voice is None and not request.instruct:
            voice = self._default_voice()
            if voice is not None:
                request = dataclasses.replace(request, voice=voice)
        engine_name = voice.engine if voice else "omnivoice"
        engine = self.engines.get(engine_name)
        if engine is None:
            raise RuntimeError(f"O motor de voz {engine_name!r} não está disponível.")
        return engine, request

    def cache_identity(self, request: VoiceRequest) -> str:
        """Identidade do motor que de fato fala, para o cache não misturar falas de motores diferentes."""
        engine, resolved = self._target(request)
        identity = getattr(engine, "cache_identity", None)
        base = identity(resolved) if identity else engine.engine_id
        if request.voice is None and resolved.voice is not None:
            base = f"{base}|{resolved.voice.fingerprint()}"  # trocar a voz padrão não reaproveita falas da anterior
        return base

    def synthesize(self, request: VoiceRequest) -> Speech:
        engine, resolved = self._target(request)
        return engine.synthesize(resolved)

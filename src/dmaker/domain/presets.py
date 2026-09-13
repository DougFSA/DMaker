"""Presets de plataforma: dimensões, fps, limites, codificação e zonas seguras.

Zonas seguras (px, na resolução do preset) = área coberta pela interface do app
(nome do perfil, legenda, botões de curtir/comentar). Texto importante fica fora delas.
Limites de duração são avisos, não bloqueios: as plataformas mudam esses números.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class SafeZone:
    top: int = 0
    bottom: int = 0
    left: int = 0
    right: int = 0


@dataclass(frozen=True)
class Preset:
    id: str
    platform: str
    name: str
    width: int
    height: int
    fps: float = 30
    max_duration: float | None = None  # segundos; None = sem limite prático
    crf: int = 18
    maxrate_k: int = 12000  # kbps
    audio_k: int = 192
    safe: SafeZone = SafeZone()
    notes: str = ""

    @property
    def aspect(self) -> float:
        return self.width / self.height

    @property
    def orientation(self) -> str:
        if abs(self.aspect - 1) < 0.02:
            return "quadrado"
        return "vertical" if self.aspect < 1 else "horizontal"

    @property
    def short_side(self) -> int:
        return min(self.width, self.height)

    @property
    def level(self) -> str:
        return "5.1" if self.width * self.height > 1920 * 1080 or self.fps > 30 else "4.2"

    def preview(self, short_side: int = 540) -> Preset:
        """Versão reduzida para renders rápidos de conferência."""
        k = short_side / self.short_side
        w = int(round(self.width * k / 2)) * 2
        h = int(round(self.height * k / 2)) * 2
        safe = SafeZone(
            *(int(v * k) for v in (self.safe.top, self.safe.bottom, self.safe.left, self.safe.right))
        )
        return replace(self, id=self.id, width=w, height=h, crf=28, maxrate_k=2500, audio_k=96, safe=safe)


V = SafeZone  # atalho

_LIST: list[Preset] = [
    # Instagram
    Preset(
        "instagram/reels",
        "Instagram",
        "Reels",
        1080,
        1920,
        30,
        180,
        18,
        12000,
        192,
        V(220, 420, 60, 150),
        "9:16. Até 3 min. Legenda e botões cobrem a base e a direita.",
    ),
    Preset(
        "instagram/stories",
        "Instagram",
        "Stories",
        1080,
        1920,
        30,
        60,
        18,
        12000,
        192,
        V(250, 300, 60, 60),
        "9:16. Até 60 s por story. Topo (perfil) e base (resposta) cobertos.",
    ),
    Preset(
        "instagram/feed-portrait",
        "Instagram",
        "Feed 4:5",
        1080,
        1350,
        30,
        90,
        18,
        10000,
        192,
        V(40, 40, 40, 40),
        "4:5, ocupa mais tela no feed. Vídeo de feed vira Reels ao publicar.",
    ),
    Preset(
        "instagram/feed-square",
        "Instagram",
        "Feed 1:1",
        1080,
        1080,
        30,
        90,
        18,
        8000,
        192,
        V(40, 40, 40, 40),
        "1:1. Bom para reaproveitar em vários canais.",
    ),
    Preset(
        "instagram/feed-landscape",
        "Instagram",
        "Feed 16:9",
        1080,
        608,
        30,
        90,
        18,
        6000,
        192,
        V(30, 30, 40, 40),
        "Horizontal no feed (max 1.91:1).",
    ),
    # Facebook
    Preset(
        "facebook/reels",
        "Facebook",
        "Reels",
        1080,
        1920,
        30,
        90,
        18,
        12000,
        192,
        V(220, 420, 60, 150),
        "9:16. Até 90 s.",
    ),
    Preset(
        "facebook/stories",
        "Facebook",
        "Stories",
        1080,
        1920,
        30,
        20,
        18,
        12000,
        192,
        V(250, 300, 60, 60),
        "9:16. Recomendado ate 20 s por story (anúncios); vídeos maiores são divididos.",
    ),
    Preset(
        "facebook/feed-portrait",
        "Facebook",
        "Feed 4:5",
        1080,
        1350,
        30,
        None,
        18,
        10000,
        192,
        V(40, 40, 40, 40),
        "4:5 no feed. Sem limite prático de duração.",
    ),
    Preset(
        "facebook/feed-square",
        "Facebook",
        "Feed 1:1",
        1080,
        1080,
        30,
        None,
        18,
        8000,
        192,
        V(40, 40, 40, 40),
        "1:1 no feed.",
    ),
    Preset(
        "facebook/feed-landscape",
        "Facebook",
        "Feed 16:9",
        1920,
        1080,
        30,
        None,
        18,
        12000,
        192,
        V(40, 40, 40, 40),
        "16:9 no feed e em anúncios in-stream.",
    ),
    # YouTube
    Preset(
        "youtube/shorts",
        "YouTube",
        "Shorts",
        1080,
        1920,
        30,
        180,
        18,
        12000,
        192,
        V(200, 480, 60, 150),
        "9:16. Até 3 min. Título e canal cobrem a base; botões à direita.",
    ),
    Preset(
        "youtube/video",
        "YouTube",
        "Vídeo 1080p",
        1920,
        1080,
        30,
        None,
        18,
        16000,
        256,
        V(60, 100, 60, 60),
        "16:9 Full HD. Barra de progresso e controles na base.",
    ),
    Preset(
        "youtube/video-4k",
        "YouTube",
        "Vídeo 4K",
        3840,
        2160,
        30,
        None,
        18,
        45000,
        256,
        V(120, 200, 120, 120),
        "16:9 4K UHD. Use quando a fonte for 4K.",
    ),
    # Outros úteis no Brasil
    Preset(
        "tiktok/video",
        "TikTok",
        "Vídeo",
        1080,
        1920,
        30,
        600,
        18,
        12000,
        192,
        V(200, 500, 60, 150),
        "9:16. Interface grande na base e à direita.",
    ),
    Preset(
        "whatsapp/status",
        "WhatsApp",
        "Status",
        1080,
        1920,
        30,
        30,
        20,
        8000,
        128,
        V(200, 220, 60, 60),
        "9:16. Ate 30 s. O WhatsApp recomprime, então não vale bitrate alto.",
    ),
    Preset(
        "linkedin/feed-square",
        "LinkedIn",
        "Feed 1:1",
        1080,
        1080,
        30,
        600,
        18,
        8000,
        192,
        V(40, 40, 40, 40),
        "1:1. Público B2B.",
    ),
    Preset(
        "linkedin/feed-landscape",
        "LinkedIn",
        "Feed 16:9",
        1920,
        1080,
        30,
        600,
        18,
        12000,
        192,
        V(40, 40, 40, 40),
        "16:9.",
    ),
]

PRESETS: dict[str, Preset] = {p.id: p for p in _LIST}

ALIASES: dict[str, str] = {
    "reels": "instagram/reels",
    "reel": "instagram/reels",
    "stories": "instagram/stories",
    "story": "instagram/stories",
    "feed": "instagram/feed-portrait",
    "square": "instagram/feed-square",
    "quadrado": "instagram/feed-square",
    "shorts": "youtube/shorts",
    "short": "youtube/shorts",
    "youtube": "youtube/video",
    "yt": "youtube/video",
    "4k": "youtube/video-4k",
    "tiktok": "tiktok/video",
    "status": "whatsapp/status",
    "whatsapp": "whatsapp/status",
    "linkedin": "linkedin/feed-square",
    "fb": "facebook/feed-portrait",
    "facebook": "facebook/feed-portrait",
}


def get_preset(name: str) -> Preset:
    key = name.strip().lower()
    key = ALIASES.get(key, key)
    if key not in PRESETS:
        options = ", ".join(sorted(PRESETS))
        raise KeyError(f"Preset desconhecido: {name!r}. Opções: {options}")
    return PRESETS[key]


def list_presets(platform: str | None = None) -> list[Preset]:
    items = list(_LIST)
    if platform:
        items = [
            p
            for p in items
            if p.platform.lower() == platform.lower() or p.id.startswith(platform.lower() + "/")
        ]
    return items

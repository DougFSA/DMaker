"""Monta a spec do casamento comunitário a partir da lista de cortes (tempo da sessão -> câmera).
Resolve a câmera para o arquivo que cobre o intervalo, parte o corte nas fronteiras de arquivo e
desliga o áudio do clipe onde a câmera 2 (áudio bom) cobre; nas lacunas dela fica o áudio da câmera 1."""
import json
import sys
from pathlib import Path

V = "D:/casamento comunitario 15-08/Videos"
CAM1 = [
    ("c1a", f"{V}/Camera1/20260815_110334.mp4", 0.0, 589.117),
    ("c1b", f"{V}/Camera1/20260815_111336.mp4", 601.738, 65.251),
    ("c1c", f"{V}/Camera1/20260815_111503.mp4", 688.454, 61.329),
    ("c1d", f"{V}/Camera1/20260815_111628.mp4", 773.695, 41.561),
    ("c1e", f"{V}/Camera1/20260815_111740.mp4", 846.060, 2806.135),
    ("c1f", f"{V}/Camera1/20260815_120431.mp4", 3656.239, 1117.061),
    ("c1g", f"{V}/Camera1/20260815_122328.mp4", 4793.599, 541.556),
]
CAM2 = [
    ("c2a", f"{V}/Camera2/MVI_7830.MP4", 19.526, 405.772),
    ("c2b", f"{V}/Camera2/MVI_7831-003.MP4", 469.720, 1799.064),
    ("c2c", f"{V}/Camera2/MVI_7832.MP4", 2303.787, 1155.388),
    ("c2d", f"{V}/Camera2/MVI_7833-002.MP4", 3464.148, 1759.691),
]
CAMS = {1: CAM1, 2: CAM2}

# (início, fim, câmera, momento)
CUTS = [
    (12, 95, 1, "acolhida"), (95, 125, 2, "acolhida"), (125, 200, 1, "entrada"), (200, 212, 2, "entrada"),
    (212, 240, 1, "entrada"), (240, 262, 2, "entrada"), (262, 398, 1, "entrada"), (398, 425.3, 2, "entrada"),
    (425.3, 512, 1, "entrada"), (512, 585, 1, "entrada noiva 1"), (585, 612, 2, "entrada"), (612, 667, 1, "entrada noiva 2"),
    (667, 690, 2, "entrada"), (690, 749.5, 1, "entrada noiva 3"), (749.5, 775, 2, "entrada"), (775, 815, 1, "entrada noiva 4"),
    (815, 846.5, 2, "saudacao"), (846.5, 876, 1, "saudacao"), (876, 935, 2, "saudacao"), (935, 958, 1, "saudacao"), (958, 982, 2, "saudacao"),
    (982, 1000, 1, "primeira leitura"), (1000, 1060, 2, "primeira leitura"), (1060, 1095, 1, "primeira leitura"),
    (1095, 1110, 2, "salmo"), (1110, 1160, 1, "salmo"), (1160, 1230, 2, "salmo"), (1230, 1280, 1, "salmo"), (1280, 1345, 2, "salmo"),
    (1345, 1385, 1, "evangelho"), (1385, 1450, 2, "evangelho"), (1450, 1490, 1, "evangelho"), (1490, 1510, 2, "evangelho"), (1510, 1548, 1, "homilia"),
    (1548, 1575, 2, "homilia reacao"), (1575, 1640, 1, "homilia"), (1640, 1665, 2, "homilia reacao"), (1665, 1730, 1, "homilia"),
    (1730, 1750, 2, "homilia reacao"), (1750, 1810, 1, "homilia"), (1810, 1860, 2, "homilia"), (1860, 1930, 1, "homilia"),
    (1930, 1980, 2, "homilia"), (1980, 2050, 1, "homilia"), (2050, 2100, 2, "homilia"), (2100, 2170, 1, "homilia"),
    (2170, 2220, 2, "homilia"), (2220, 2303.787, 1, "homilia"),
    (2303.787, 2325, 2, "consentimento"), (2325, 2360, 1, "consentimento"), (2360, 2394, 2, "consentimento Daniel e Bruna"),
    (2394, 2455, 1, "consentimento Matheus e Gabriele, Antonio Carlos e Giovana"), (2455, 2478, 2, "consentimento"),
    (2478, 2498, 2, "consentimento Luis Carlos e Debora"), (2498, 2547, 1, "consentimento Luis Carlos e Debora"),
    (2547, 2600, 2, "votos Daniel e Bruna"), (2600, 2616, 1, "votos Daniel e Bruna"), (2616, 2684, 2, "votos Matheus e Gabriele"),
    (2684, 2700, 1, "votos Antonio Carlos e Giovana"), (2700, 2722, 2, "votos Giovana"),
    (2722, 2765, 1, "votos Luis Carlos e Debora"), (2765, 2825, 2, "votos e bencao"),
    (2825, 2848, 1, "aliancas"), (2848, 2870, 2, "aliancas entrada"), (2870, 2905, 1, "aliancas entrada"), (2905, 2925, 2, "aliancas entrada"),
    (2925, 2995, 1, "aliancas entrada"), (2995, 3062, 2, "bencao das aliancas"), (3062, 3125, 1, "aliancas Daniel e Bruna"),
    (3125, 3160, 2, "aliancas Bruna"), (3160, 3210, 1, "aliancas Matheus e Gabriele"), (3210, 3265, 2, "aliancas Gabriele, Antonio Carlos"),
    (3265, 3340, 1, "aliancas Giovana, Luis Carlos"), (3340, 3420, 2, "aliancas Debora e aplausos"), (3420, 3470, 1, "preces"),
    (3470, 3500, 2, "preces"), (3500, 3532, 1, "preces"),
    (3532, 3575, 2, "bencao nupcial"), (3575, 3635, 1, "bencao nupcial"), (3635, 3700, 2, "bencao nupcial"),
    (3700, 3735, 1, "assinaturas"), (3735, 3765, 2, "assinaturas"), (3765, 3800, 1, "assinaturas"), (3800, 3830, 2, "assinaturas"),
    (3830, 3870, 1, "assinaturas"), (3870, 3900, 2, "assinaturas"), (3900, 3945, 1, "assinaturas"), (3945, 3968, 2, "assinaturas"),
    (3968, 4000, 2, "Sagrada Familia"), (4000, 4015, 1, "Sagrada Familia"), (4015, 4032, 2, "Sagrada Familia"), (4032, 4070, 1, "Sagrada Familia"),
    (4070, 4105, 2, "Sagrada Familia"), (4105, 4135, 1, "Sagrada Familia"), (4135, 4160, 2, "Sagrada Familia"),
    (4160, 4200, 1, "Ave Maria"), (4200, 4240, 2, "Ave Maria"), (4240, 4275, 1, "bencao final"), (4275, 4306, 2, "bencao final"),
    (4306, 4330, 1, "beijo"), (4330, 4365, 2, "abracos"), (4365, 4395, 1, "abracos"),
    (4395, 4430, 2, "abracos"), (4430, 4460, 1, "abracos"), (4460, 4520, 2, "abracos"), (4520, 4550, 1, "abracos"),
    (4550, 4610, 2, "abracos"), (4610, 4640, 1, "abracos"), (4640, 4700, 2, "abracos"), (4700, 4730, 1, "abracos"),
    (4730, 4800, 2, "abracos"), (4800, 4860, 1, "fotos no altar"), (4860, 4900, 2, "cumprimentos"), (4900, 4960, 1, "fotos no altar"),
    (4960, 5000, 2, "cumprimentos"), (5000, 5060, 1, "fotos no altar"), (5060, 5100, 2, "cumprimentos"), (5100, 5180, 1, "fotos no altar"),
    (5180, 5223.839, 2, "cumprimentos"), (5223.839, 5312, 1, "saida do ultimo casal"),
]


def covering(cam, t0, t1):
    """Arquivos da câmera que cobrem [t0, t1], em ordem; erro se sobrar buraco."""
    parts = []
    t = t0
    for name, path, off, dur in cam:
        end = off + dur
        if end <= t or off >= t1:
            continue
        if off > t + 0.01:
            raise ValueError(f"câmera sem cobertura em {t:.1f}-{off:.1f}")
        seg_end = min(end, t1)
        parts.append((name, t, seg_end))
        t = seg_end
        if t >= t1:
            break
    if t < t1 - 0.05:  # tolerância: fim de arquivo arredondado
        raise ValueError(f"câmera sem cobertura em {t:.1f}-{t1:.1f}")
    return parts


def cam2_covers(t0, t1):
    """Se o áudio da câmera 2 existe em todo o intervalo (senão fica o áudio da câmera 1)."""
    return any(off <= t0 + 0.01 and off + dur >= t1 - 0.01 for _, _, off, dur in CAM2)


# ganho do áudio do celular em cada lacuna da câmera 2, medido contra os trechos vizinhos dela
GAP_GAIN = {12: 1.35, 425.3: 1.45, 2268.784: 1.55, 3459.175: 2.6, 5223.839: 0.9}


def split_at_cam2_edges(t0, t1):
    edges = sorted({e for _, _, off, dur in CAM2 for e in (off, off + dur) if t0 < e < t1})
    points = [t0] + edges + [t1]
    return list(zip(points, points[1:]))


sources = {}
for cam in (CAM1, CAM2):
    for name, path, off, dur in cam:
        sources[name] = {"src": path, "sync": round(off, 3), "label": Path(path).name}
timeline = [
    {"type": "image", "src": "cards/abertura.png", "duration": 4.5, "motion": "none", "label": "cartao de abertura"},
    {"type": "image", "src": "cards/creditos.png", "duration": 6.5, "motion": "none", "transition": {"type": "dissolve", "duration": 1.5}, "label": "creditos"},
]
first = True
prev_end = None
for t0, t1, cam, label in CUTS:
    if prev_end is not None and abs(t0 - prev_end) > 0.01:
        raise ValueError(f"corte descontínuo em {prev_end} -> {t0}")
    prev_end = t1
    for a, b in split_at_cam2_edges(t0, t1):
        for name, s, e in covering(CAMS[cam], a, b):
            clip = {
                "type": "clip", "source": name, "start": round(s, 3), "end": round(e, 3), "label": label,
                "transition": {"type": "dissolve", "duration": 2.0} if first else {"type": "cut"},
            }
            if cam2_covers(s, e):
                clip["mute"] = True
            else:
                clip["volume"] = GAP_GAIN.get(round(s, 3), 1.0)
            timeline.append(clip)
            first = False
timeline.append({
    "type": "image", "src": "cards/encerramento.png", "duration": 15.0, "motion": "none",
    "transition": {"type": "dissolve", "duration": 1.5}, "label": "cartao de encerramento",
})
VIDEO_OFFSET = 4.5 + 6.5 - 1.5 - 2.0 - CUTS[0][0]  # tempo do vídeo = tempo da sessão + isto (dissolves descontados)
last_end = CUTS[-1][1] + VIDEO_OFFSET
total = last_end - 1.5 + 15.0
ending_start = last_end - 20  # a trilha volta enquanto o último casal sai
SONG_LENGTH = 201.76
ending_start_at = SONG_LENGTH - (total - ending_start) - 0.5  # termina junto com a música
spec = {
    "name": "casamento-comunitario-15-08",
    "output": {"preset": "youtube/video", "quality": "high"},
    "sources": sources,
    "master": "c1a",
    "timeline": timeline,
    "audio": {
        "tracks": [{"source": n, "volume": 1.0} for n in ("c2a", "c2b", "c2c", "c2d")],
        "music": {
            "src": "C:/Users/Douglas Vasconcelos/Videos/4K Video Downloader+/Can't Help Falling In Love.m4a",
            "volume": 0.8,
            "loop": False,
            "ducking": False,
            "spans": [
                {"start": 0, "end": 16, "start_at": 0, "fade_in": 0.5, "fade_out": 7.0},
                {"start": round(ending_start, 3), "end": None, "start_at": round(ending_start_at, 3), "fade_in": 5.0, "fade_out": 5.0},
            ],
        },
        "normalize": "two-pass",
    },
}
out = Path(sys.argv[1])
out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
unmuted = [c for c in timeline if c["type"] == "clip" and not c.get("mute")]
print(len(timeline), "trechos;", len(unmuted), "com audio da camera 1:", [(c["start"], c["end"]) for c in unmuted])

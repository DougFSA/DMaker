"""As licenças do que vai no pacote: a lista (dado puro) e o texto do aviso que o instalador mostra e instala."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .manifest import default_model_ids


@dataclass(frozen=True)
class LicenseItem:
    name: str
    license: str
    redistributable: bool  # pode ir no pacote (False: precisa de uma decisão de quem publica)
    source: str  # de onde veio (e, quando a licença pede, onde está o código-fonte)
    note: str = ""
    non_commercial: bool = False  # vai no pacote, mas a licença proíbe o uso comercial: o aviso acompanha


# Um item por componente que o `build` embute além do código do DMaker (MIT). Os modelos seguem o registro
# (`domain/models.py`); a licença de cada um foi conferida na página do modelo ou no pacote que o baixa.
COMMON_ITEMS: tuple[LicenseItem, ...] = (
    LicenseItem(
        "Python 3.13 (python-build-standalone)",
        "PSF License",
        True,
        "https://github.com/astral-sh/python-build-standalone ; https://docs.python.org/3/license.html",
        "As bibliotecas que o build do Python embute trazem as licenças delas em python/LICENSE.txt.",
    ),
    LicenseItem(
        "Ollama 0.40.16 (só o programa, nenhum modelo)",
        "MIT",
        True,
        "https://github.com/ollama/ollama",
        "Instalado junto só se a máquina ainda não tiver o programa.",
    ),
    LicenseItem(
        "PyTorch, torchaudio e demais pacotes Python",
        "BSD-3-Clause, MIT, Apache-2.0 e similares, cada um com a sua",
        True,
        "Cada pacote traz a licença na pasta *.dist-info em site-packages",
    ),
    LicenseItem("Poppins (fonte)", "SIL Open Font License 1.1", True, "assets/fonts/OFL-Poppins.txt"),
    LicenseItem(
        "three.js, lottie-web e rough-notation (composição em HTML)",
        "MIT",
        True,
        "assets/html/LICENSE-*.txt",
    ),
    LicenseItem(
        "Regras de boca em português do TalkingHead (lipsync-pt_br.mjs, portadas para Python)",
        "MIT",
        True,
        "https://github.com/met4citizen/TalkingHead ; src/dmaker/persona/visemes.py",
        "O aviso da licença MIT acompanha o código portado (persona/visemes.py). A persona 2D é desenhada pelo DMaker, "
        "sem arquivo de terceiros.",
    ),
    LicenseItem(
        "TalkingHead (talkinghead.mjs, dynamicbones.mjs, retargeter.mjs): anima a persona 3D",
        "MIT",
        True,
        "https://github.com/met4citizen/TalkingHead (commit 1563de1) ; assets/html/persona/3d/vendor/talkinghead/",
        "A licença MIT acompanha os arquivos (LICENSE-talkinghead.txt).",
    ),
    LicenseItem(
        "Addons do three.js r185 usados pelo TalkingHead (GLTFLoader, OrbitControls e outros)",
        "MIT",
        True,
        "https://github.com/mrdoob/three.js (tag r185, examples/jsm) ; assets/html/persona/3d/vendor/three-addons/",
        "A licença MIT acompanha os arquivos (LICENSE-three-addons.txt).",
    ),
    LicenseItem(
        "Personagem 3D mpfb.glb (feito com Blender e MPFB)",
        "CC0 1.0 (domínio público)",
        True,
        "https://github.com/met4citizen/TalkingHead/blob/main/avatars/mpfb.glb",
        "Não vai no pacote nem no git: o `dmaker models download persona3d-mpfb` baixa para cache/models, do commit "
        "fixado e conferido por SHA-256. O README do TalkingHead diz que os assets MakeHuman por trás do MPFB são "
        '"CC0/CC-BY"; conferidos um a um nas páginas dos pacotes da comunidade MakeHuman, os que o mpfb.glb usa '
        "(corpo, olhos, sobrancelhas e cílios Mindfront, dentes, língua, cabelo ponytail01 e a roupa "
        "female_casualsuit01) estão todos como CC0, e o README declara o avatar como CC0. Não achamos nenhum item "
        "CC-BY, então não há aviso de atribuição obrigatório; a página da textura da pele "
        "(young_lightskinned_female) não lista o item pelo nome, mas é do mesmo pacote de sistema CC0. A textura da "
        "roupa, que traz um logotipo do MakeHuman, nunca aparece: o DMaker a troca por uma cor lisa. Os outros "
        "avatares do TalkingHead são de uso não comercial e as animações Mixamo não podem ser redistribuídas: o "
        "DMaker não usa nenhum deles.",
    ),
    LicenseItem(
        "ditto-talkinghead (código vendorizado): anima a persona realista",
        "Apache-2.0",
        True,
        "https://github.com/antgroup/ditto-talkinghead (commit c3e47ee) ; src/dmaker/vendor/ditto/",
        "O texto da licença (LICENSE) e a lista do que mudamos (NOTICE) acompanham o código. O InsightFace, que o "
        "ditto original usa, fica de fora (uso não comercial): a caixa do rosto vem do MediaPipe.",
    ),
    LicenseItem(
        "Pesos do ditto-talkinghead (persona realista)",
        "Apache-2.0",
        True,
        "https://huggingface.co/digital-avatar/ditto-talkinghead (revisão e4a2f60328ee7c32af585ac4b3cce299e4c8e254)",
        "Não vão no pacote nem no git: o `dmaker models download persona-realista` baixa para cache/models, da "
        "revisão fixada e conferidos por SHA-256. Os modelos MediaPipe blaze_face e face_mesh constam como "
        "Apache-2.0, segundo os model cards. O landmark203 consta como MIT, vindo do LivePortrait, conforme o model "
        "card. O hubert.onnx consta como distribuído nos pesos do ditto sob Apache-2.0, com a origem da base não "
        "declarada. O InsightFace não é usado.",
    ),
    LicenseItem(
        "OpenVINO (o pacote openvino, sem o openvino-telemetry)",
        "Apache-2.0",
        True,
        "https://github.com/openvinotoolkit/openvino ; extra persona-realista do pip",
        "Roda o warp e o decoder da persona realista na GPU integrada Intel. O openvino-telemetry não é instalado: "
        "nada vai para a rede.",
    ),
    LicenseItem(
        "opencv-python-headless",
        "Apache-2.0 (o OpenCV); o pacote embute o FFmpeg sob LGPL-2.1",
        True,
        "https://github.com/opencv/opencv-python ; extra persona-realista do pip",
        "Lê, enquadra e grava as imagens da persona realista. A licença do pacote fica na pasta *.dist-info.",
    ),
)

# O que muda de um sistema para outro: o FFmpeg e o Chromium.
PLATFORM_ITEMS: dict[str, tuple[LicenseItem, ...]] = {
    "windows": (
        LicenseItem(
            "FFmpeg 9.0.2 (gyan.dev, build full)",
            "GPL v3",
            True,
            "https://www.gyan.dev/ffmpeg/builds/ ; código-fonte do build: https://github.com/FFmpeg/FFmpeg/commit/946fcce07b",
            "O texto da GPL v3 vai em bin/ffmpeg/LICENSE. O FFmpeg roda como programa separado, chamado pelo DMaker.",
        ),
        LicenseItem(
            "FFmpeg n9.0.2 (BtbN, plugins LV2)",
            "GPL v3",
            True,
            "https://github.com/BtbN/FFmpeg-Builds ; código-fonte: https://github.com/FFmpeg/FFmpeg (commit b204e94e90)",
            "O texto da GPL v3 vai em bin/ffmpeg-lv2/LICENSE.txt.",
        ),
        LicenseItem(
            "Chromium (Playwright)",
            "BSD-3-Clause e licenças de terceiros do Chromium",
            True,
            "https://www.chromium.org/ ; https://playwright.dev/",
            "As licenças de terceiros ficam em bin/playwright/chromium-*/chrome-win*/ (arquivo LICENSE).",
        ),
    ),
    "linux": (
        LicenseItem(
            "FFmpeg n9.0 (BtbN, build estático com LADSPA e LV2)",
            "GPL v3",
            True,
            "https://github.com/BtbN/FFmpeg-Builds ; código-fonte: https://github.com/FFmpeg/FFmpeg",
            "O texto da GPL v3 vai em bin/ffmpeg/LICENSE.txt. O FFmpeg roda como programa separado, chamado pelo DMaker.",
        ),
        LicenseItem(
            "Chromium (Playwright)",
            "BSD-3-Clause e licenças de terceiros do Chromium",
            True,
            "https://www.chromium.org/ ; https://playwright.dev/",
            "As licenças de terceiros ficam em bin/playwright/chromium-*/chrome-linux*/ (arquivo LICENSE).",
        ),
    ),
}

MODEL_LICENSES: dict[str, LicenseItem] = {
    "whisper-small": LicenseItem(
        "Whisper small (faster-whisper, Systran)",
        "MIT",
        True,
        "https://huggingface.co/Systran/faster-whisper-small",
    ),
    "omnivoice": LicenseItem(
        "OmniVoice (k2-fsa)",
        "CC BY-NC 4.0 (os pesos); Apache-2.0 (o código)",
        True,
        "https://huggingface.co/k2-fsa/OmniVoice",
        "Os pesos são CC BY-NC 4.0 por causa dos dados de treino (Emilia): podem ser redistribuídos com atribuição "
        "(OmniVoice, k2-fsa) e SEM fins comerciais. A página do modelo diz isso na seção License; o registro do "
        "DMaker dizia Apache-2.0, que vale só para o código.",
        non_commercial=True,
    ),
    "kokoro-fp32": LicenseItem(
        "Kokoro 82M v1.0 (kokoro-onnx)",
        "Apache-2.0",
        True,
        "https://github.com/thewh1teagle/kokoro-onnx ; https://huggingface.co/hexgrad/Kokoro-82M",
    ),
    "demucs-htdemucs": LicenseItem(
        "Demucs htdemucs (Meta)",
        "MIT",
        True,
        "https://github.com/facebookresearch/demucs",
        "A licença MIT é a do repositório do Demucs; o espelho do Hugging Face não declara outra.",
    ),
    "audioseal": LicenseItem(
        "AudioSeal (Meta)", "MIT", True, "https://github.com/facebookresearch/audioseal"
    ),
    "diarization-sherpa": LicenseItem(
        "pyannote segmentation 3.0 e CAM++ 3D-Speaker (sherpa-onnx)",
        "MIT (segmentação) e Apache-2.0 (voz)",
        True,
        "https://github.com/k2-fsa/sherpa-onnx",
    ),
    "openvoice-v2": LicenseItem(
        "OpenVoice V2 (MyShell)", "MIT", True, "https://huggingface.co/myshell-ai/OpenVoiceV2"
    ),
    "rvm-resnet50": LicenseItem(
        "Robust Video Matting resnet50",
        "GPL v3",
        True,
        "https://github.com/PeterL1n/RobustVideoMatting",
        "O DMaker lê o arquivo do modelo como dado, sem incorporá-lo ao código; o aviso e o link do código "
        "acompanham o pacote.",
    ),
}


def license_items(platform: str = "windows", excluded_models: Iterable[str] = ()) -> list[LicenseItem]:
    """A lista completa: o que é do sistema, os componentes comuns e um item por modelo padrão que vai no pacote."""
    skipped = set(excluded_models)
    models = (MODEL_LICENSES[model_id] for model_id in default_model_ids() if model_id not in skipped)
    return [*PLATFORM_ITEMS[platform], *COMMON_ITEMS, *models]


def blocked_models() -> list[str]:
    """Os modelos padrão que não podem ir no pacote sem uma decisão de quem publica."""
    return [model_id for model_id in default_model_ids() if not MODEL_LICENSES[model_id].redistributable]


def non_commercial_models(excluded_models: Iterable[str] = ()) -> list[LicenseItem]:
    """Os modelos que vão no pacote com licença de uso não comercial (o aviso vai no LICENCAS.txt e nas notas)."""
    skipped = set(excluded_models)
    return [
        MODEL_LICENSES[model_id]
        for model_id in default_model_ids()
        if model_id not in skipped and MODEL_LICENSES[model_id].non_commercial
    ]


def license_notice(version: str, platform: str = "windows", excluded_models: Iterable[str] = ()) -> str:
    """O texto de `licencas/LICENCAS.txt`, que o instalador mostra antes de instalar."""
    skipped = tuple(excluded_models)
    lines = [
        f"DMaker {version}: licenças do que vai neste pacote",
        "=" * 60,
        "",
        "O código do DMaker é MIT. Este pacote leva, além dele, os componentes abaixo, cada um com a sua licença.",
        "",
    ]
    restricted = non_commercial_models(skipped)
    if restricted:
        lines += ["AVISO DE USO NÃO COMERCIAL"]
        lines += [
            f"  {item.name}: {item.license}. Os pesos vão no pacote com atribuição, mas não podem ser usados com fins comerciais."
            for item in restricted
        ]
        lines.append("")
    for item in license_items(platform, skipped):
        lines += [f"* {item.name}", f"  Licença: {item.license}", f"  Origem: {item.source}"]
        if item.note:
            lines.append(f"  Nota: {item.note}")
        if item.non_commercial:
            lines.append("  ATENÇÃO: uso somente não comercial, com atribuição.")
        elif not item.redistributable:
            lines.append("  ATENÇÃO: uso restrito, leia a licença antes de usar este componente.")
        lines.append("")
    if skipped:
        lines += [
            "Modelos que NÃO vão neste pacote e baixam no primeiro uso: " + ", ".join(skipped) + ".",
            "",
        ]
    lines += [
        "Não vão no pacote: os modelos de linguagem do Ollama (você baixa o que quiser), as suas vozes e projetos,",
        "e plugins de terceiros.",
        "",
        "Mais detalhes de código de terceiros: THIRD_PARTY.md (no repositório do DMaker).",
        "",
    ]
    return "\n".join(lines)

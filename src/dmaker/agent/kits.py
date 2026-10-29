"""Kits de ferramentas do agente local: dado puro que diz o que cada tipo de pedido enxerga.

Um modelo pequeno se perde com 70 ferramentas e gasta o contexto lendo esquemas. Por isso cada pedido cai num
kit (ver `triage.py`) e o modelo só vê as ferramentas e o manual curto daquele kit. Os kits podem citar
ferramentas que o servidor MCP ainda não tem (as de cards em andamento): quem monta a lista filtra pelo que o
servidor expõe de fato. Um teste prende que toda ferramenta do servidor está num kit ou na lista de excluídas,
com o motivo, para uma ferramenta nova não ficar esquecida.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Kit:
    """Um conjunto de ferramentas para um tipo de pedido.

    `keywords` são radicais sem acento: uma palavra casa por prefixo ("legend" pega "legenda" e "legendas");
    uma expressão de várias palavras casa inteira e vale um ponto por palavra. `tasks` são as tarefas do manual cujos exemplos
    viram o manual curto do kit.
    """

    name: str
    title: str
    description: str
    tools: tuple[str, ...]
    keywords: tuple[str, ...]
    tasks: tuple[str, ...]


# Valem para qualquer pedido: descobrir o que é um arquivo, acompanhar uma tarefa longa e consultar o manual.
BASE_TOOLS: tuple[str, ...] = ("probe_media", "job_status", "search_manual")

KITS: tuple[Kit, ...] = (
    Kit(
        name="editing",
        title="Edição e render",
        description=(
            "Criar o vídeo (reel, short, story, explicativo), cortar pausas e vícios, editar o projeto, "
            "renderizar, exportar para outras plataformas e conferir o resultado."
        ),
        tools=(
            "list_templates",
            "new_from_template",
            "quick_edit",
            "build_explainer_video",
            "autocut",
            "cut_pauses_and_caption",
            "list_cuts",
            "undo_cut",
            "list_projects",
            "get_project",
            "validate_project",
            "edit_project",
            "timeline_view",
            "render_project",
            "export_project",
            "qa_report",
            "presets",
            "brands",
        ),
        keywords=(
            "reel",
            "short",
            "story",
            "stories",
            "tiktok",
            "instagram",
            "facebook",
            "youtube",
            "whatsapp",
            "corta",
            "cortar",
            "corte",
            "pausa",
            "vicio",
            "repeticao",
            "render",
            "exporta",
            "template",
            "modelo pronto",
            "projeto",
            "marca",
            "explicativ",
            "edita",
            "gancho",
            "logo",
            "musica",
            "trilha",
            "transicao",
            "look",
            "cta",
            "formato",
            "qa",
            "preset",
        ),
        tasks=("reel", "modelo", "cortar-pausas", "explicativo", "exportar", "conferir-video"),
    ),
    Kit(
        name="captions",
        title="Legendas",
        description="Ler, transcrever e corrigir as legendas de um vídeo ou de um projeto.",
        tools=(
            "read_captions",
            "fix_captions",
            "transcribe_media",
            "get_project",
            "validate_project",
            "edit_project",
            "render_project",
            "qa_report",
        ),
        keywords=("legend", "transcri", "subtitle", "caption", "srt", "palavra errada"),
        tasks=("corrigir-legenda", "legenda-caixa"),
    ),
    Kit(
        name="voice",
        title="Voz e narração",
        description=(
            "Narrar um texto, pôr a narração num projeto, clonar ou criar uma voz, ensinar a pronúncia de "
            "um nome e conferir se um áudio foi gerado pelo DMaker."
        ),
        tools=(
            "narrate_into_project",
            "synthesize_speech",
            "list_voices",
            "clone_voice",
            "design_voice",
            "voice_queue_add",
            "voice_queue_list",
            "pronunciation",
            "verify_watermark",
            "list_projects",
            "get_project",
            "validate_project",
            "render_project",
        ),
        keywords=(
            "narr",
            "voz",
            "clon",
            "locu",
            "pronunc",
            "roteiro",
            "audiobook",
            "fala sintetica",
            "marca dagua",
            "dora",
        ),
        tasks=("narrar", "narracao-no-projeto", "clonar-voz", "desenhar-voz", "pronuncia", "verificar-audio"),
    ),
    Kit(
        name="dubbing",
        title="Dublagem",
        description="Dublar um vídeo para outro idioma, revisar as traduções e exportar as trilhas.",
        tools=(
            "dub_prepare",
            "dub_get",
            "dub_update_segment",
            "dub_retranslate",
            "dub_render",
            "dub_stems",
            "list_voices",
        ),
        keywords=("dubl", "traduz", "idioma", "legendado"),
        tasks=("dublar", "dublar-varias-pessoas", "dublar-esticar", "dublar-trilhas"),
    ),
    Kit(
        name="speech",
        title="Correção de fala e isolamento",
        description=(
            "Isolar a voz da música e do ruído, corrigir uma palavra dita errada sem regravar e trocar a "
            "voz de uma gravação."
        ),
        tools=("speech_words", "fix_speech", "convert_voice", "isolate_vocals", "list_voices"),
        keywords=(
            "isola",
            "isolar",
            "isola a voz",
            "isolar a voz",
            "isolar voz",
            "separa a voz",
            "separar a voz",
            "separar voz",
            "vocal",
            "ruido",
            "regrav",
            "corrige a fala",
            "corrigir a fala",
            "troca a voz",
            "trocar a voz",
            "converte a voz",
        ),
        tasks=("isolar-voz", "corrigir-fala", "trocar-voz"),
    ),
    Kit(
        name="multicam",
        title="Multicâmera",
        description="Sincronizar câmeras pelo áudio e montar o vídeo de um evento (casamento) com duas câmeras.",
        tools=(
            "sync_sources",
            "plan_multicam",
            "list_templates",
            "new_from_template",
            "get_project",
            "validate_project",
            "timeline_view",
            "render_project",
            "qa_report",
        ),
        keywords=("camera", "multicam", "casamento", "cerimonia", "altar", "pascom", "sincroniz"),
        tasks=("multicam",),
    ),
    Kit(
        name="compositions",
        title="Composições e infográficos",
        description=(
            "Pôr sobre o vídeo um infográfico pronto com parâmetros (contador, gráfico, barra) ou uma "
            "composição em HTML."
        ),
        tools=(
            "list_infographics",
            "add_infographic",
            "render_html_frame",
            "add_html_overlay",
            "list_projects",
            "get_project",
            "validate_project",
            "edit_project",
            "timeline_view",
            "render_project",
        ),
        keywords=("infograf", "grafico", "contador", "html", "composic", "overlay", "sobreposic", "animac"),
        tasks=(),
    ),
    Kit(
        name="batch",
        title="Lote",
        description="Gerar vários vídeos de uma planilha (CSV, XLSX ou JSON) sobre o mesmo modelo.",
        tools=(
            "validate_batch",
            "run_batch",
            "resume_batch",
            "pause_batch",
            "batch_status",
            "list_templates",
        ),
        keywords=("lote", "planilha", "csv", "xlsx", "varios videos", "em serie"),
        tasks=("lote",),
    ),
)

# Ferramentas do servidor que nenhum kit oferece, cada uma com o motivo. O teste de cobertura exige que uma
# ferramenta nova entre num kit ou aqui: assim o agente nunca ganha (nem perde) uma função sem ninguém decidir.
EXCLUDED_TOOLS: dict[str, str] = {
    "dmaker_guide": "o guia inteiro não cabe no contexto de um modelo pequeno; vale o manual curto do kit",
    "spec_schema": "o esquema da spec é enorme; o agente edita por template e por edit_project",
    "save_project": "exige escrever a spec inteira à mão; o agente cria o projeto por new_from_template",
    "clean_cache": "apaga o cache que um render em andamento pode estar usando; só por comando explícito",
    "contact_sheet": "devolve imagem e o modelo local de texto não enxerga; a conferência é o qa_report",
    "frames": "devolve imagem e o modelo local de texto não enxerga; a conferência é o qa_report",
    "render_card_preview": "devolve imagem e o modelo local de texto não enxerga",
    "models": "baixa e apaga modelos grandes pela rede; é decisão de quem usa, em `dmaker models`",
    "list_jobs": "job_status com o número da tarefa já basta",
}

DEFAULT_KIT = "editing"
MAX_KITS_PER_REQUEST = 2  # um pedido que cruza kits soma no máximo dois: mais que isso estoura o contexto


def kit_by_name(name: str) -> Kit:
    for kit in KITS:
        if kit.name == name:
            return kit
    known = ", ".join(kit.name for kit in KITS)
    raise KeyError(f"Kit desconhecido: {name!r}. Os kits são: {known}.")


def kit_names() -> tuple[str, ...]:
    return tuple(kit.name for kit in KITS)


def kit_tool_names(kit: Kit, available: Collection[str] | None = None) -> list[str]:
    """As ferramentas do kit (as comuns primeiro), só as que o servidor expõe quando `available` é dado."""
    names = list(dict.fromkeys((*BASE_TOOLS, *kit.tools)))
    return names if available is None else [name for name in names if name in available]


def tools_for_kits(kits: Iterable[Kit], available: Collection[str] | None = None) -> list[str]:
    """A união das ferramentas de vários kits, sem repetir e na ordem em que aparecem."""
    names: list[str] = []
    for kit in kits:
        names.extend(kit_tool_names(kit, available))
    return list(dict.fromkeys(names))


def all_kit_tool_names() -> tuple[str, ...]:
    """Toda ferramenta que algum kit cita: o que o agente local pode enxergar, em algum pedido."""
    return tuple(tools_for_kits(KITS))

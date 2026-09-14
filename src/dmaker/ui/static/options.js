"use strict";
/*
 * DMaker - listas de opções e constantes compartilhadas entre app.js (formulário "Propriedades")
 * e filters.js (painel "Filtros" da linha do tempo). Um só lugar para não duplicar os enums do
 * schema (src/dmaker/domain/spec.py) em dois arquivos que precisam ficar em sincronia.
 */

const QUALITY_OPTIONS = [
  { value: "high", label: "Alta" },
  { value: "medium", label: "Média" },
  { value: "draft", label: "Rascunho" },
];

const ENCODER_OPTIONS = [
  { value: "x264", label: "x264 (CPU)" },
  { value: "nvenc", label: "NVENC (Nvidia)" },
  { value: "amf", label: "AMF (AMD)" },
  { value: "qsv", label: "QSV (Intel)" },
];

const REFRAME_MODE_OPTIONS = [
  { value: "auto", label: "Automático" },
  { value: "crop", label: "Cortar" },
  { value: "pad", label: "Preencher com barras" },
  { value: "blur", label: "Fundo desfocado" },
  { value: "brand", label: "Fundo da marca" },
  { value: "stretch", label: "Esticar" },
];

const TRANSITION_OPTIONS = [
  { value: "cut", label: "Corte seco" },
  { value: "fade", label: "Fade" },
  { value: "dissolve", label: "Dissolve" },
  { value: "wipeleft", label: "Wipe esquerda" },
  { value: "wiperight", label: "Wipe direita" },
  { value: "wipeup", label: "Wipe cima" },
  { value: "wipedown", label: "Wipe baixo" },
  { value: "slideleft", label: "Slide esquerda" },
  { value: "slideright", label: "Slide direita" },
  { value: "slideup", label: "Slide cima" },
  { value: "slidedown", label: "Slide baixo" },
  { value: "smoothleft", label: "Smooth esquerda" },
  { value: "circleopen", label: "Círculo abrindo" },
  { value: "zoomin", label: "Zoom in" },
  { value: "fadeblack", label: "Fade para preto" },
  { value: "fadewhite", label: "Fade para branco" },
  { value: "pixelize", label: "Pixelizar" },
];

const IMAGE_MOTION_OPTIONS = [
  { value: "none", label: "Nenhum" },
  { value: "zoom-in", label: "Zoom in" },
  { value: "zoom-out", label: "Zoom out" },
  { value: "pan-left", label: "Pan esquerda" },
  { value: "pan-right", label: "Pan direita" },
];

const CARD_MOTION_OPTIONS = [
  { value: "none", label: "Nenhum" },
  { value: "zoom-in", label: "Zoom in" },
];

const VARIANT_OPTIONS = [
  { value: "", label: "Padrão do tema" },
  { value: "light", label: "Claro" },
  { value: "dark", label: "Escuro" },
];

const TEXT_ROLE_OPTIONS = [
  { value: "hook", label: "Gancho" },
  { value: "title", label: "Título" },
  { value: "subtitle", label: "Subtítulo" },
  { value: "cta", label: "Chamada para ação" },
  { value: "lower-third", label: "Legenda inferior" },
  { value: "custom", label: "Personalizado" },
];

const TEXT_POSITION_OPTIONS = [
  { value: "", label: "Automática" },
  { value: "top", label: "Topo" },
  { value: "center", label: "Centro" },
  { value: "bottom", label: "Base" },
];

const TEXT_ANIMATION_OPTIONS = [
  { value: "", label: "Padrão" },
  { value: "none", label: "Nenhuma" },
  { value: "fade", label: "Fade" },
  { value: "pop", label: "Pop" },
  { value: "slide-up", label: "Slide para cima" },
  { value: "typewriter", label: "Máquina de escrever" },
];

const IMAGE_OVERLAY_POSITION_OPTIONS = [
  { value: "top-left", label: "Topo esquerda" },
  { value: "top-right", label: "Topo direita" },
  { value: "bottom-left", label: "Base esquerda" },
  { value: "bottom-right", label: "Base direita" },
  { value: "top", label: "Topo" },
  { value: "bottom", label: "Base" },
  { value: "center", label: "Centro" },
];

const PROGRESS_POSITION_OPTIONS = [
  { value: "top", label: "Topo" },
  { value: "bottom", label: "Base" },
];

const VIDEO_OVERLAY_SHAPE_OPTIONS = [
  { value: "rect", label: "Retângulo" },
  { value: "rounded", label: "Cantos arredondados" },
  { value: "circle", label: "Círculo" },
];

const VIDEO_OVERLAY_ANIMATION_OPTIONS = [
  { value: "none", label: "Nenhuma" },
  { value: "fade", label: "Fade" },
  { value: "slide", label: "Slide" },
];

const SYNC_MODE_OPTIONS = [
  { value: "auto", label: "Automática (pelo áudio)" },
  { value: "manual", label: "Manual (segundos)" },
];

const MODEL_OPTIONS = [
  { value: "tiny", label: "Tiny" },
  { value: "base", label: "Base" },
  { value: "small", label: "Small" },
  { value: "medium", label: "Medium" },
  { value: "large-v3", label: "Large v3" },
];

const CAPTION_STYLE_MODE_OPTIONS = [
  { value: "karaoke", label: "Karaokê" },
  { value: "classic", label: "Clássico" },
  { value: "boxed", label: "Caixa" },
];

const NORMALIZE_OPTIONS = [
  { value: "two-pass", label: "Duas passadas" },
  { value: "fast", label: "Rápida" },
  { value: "off", label: "Desligada" },
];

const VIDEO_EXTENSIONS = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"];
const IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"];
const AUDIO_EXTENSIONS = [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"];

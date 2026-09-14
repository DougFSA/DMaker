"use strict";
/*
 * DMaker - painel "Filtros" (esquerda da aba Linha do tempo), estilo Shotcut: mostra os grupos de
 * campos que se aplicam ao item selecionado (ou ao projeto, quando nada está selecionado), quais
 * já saem do padrão ("aplicados"), e deixa adicionar/remover/editar grupos.
 *
 * Dirigido por dados: FILTER_CATALOG descreve os grupos e campos de cada tipo de item; um tipo
 * novo de sobreposição ou trecho entra como uma linha nova no catálogo, sem se espalhar por if/else.
 * Reaproveita os construtores de campo e as listas de opções de app.js/options.js.
 *
 * window.DMakerFilters.create(container, { applyOp, getSpec }) -> controlador:
 *   setSelection(typeKey, base)   base = caminho absoluto do item ("timeline.2", "overlays.0",
 *                                  "audio.tracks.0", "audio.music", "captions"); typeKey/base nulos
 *                                  = nada selecionado (mostra os grupos do projeto)
 *   refresh()                     redesenha com os valores atuais de getSpec() (chame após toda
 *                                  mudança bem-sucedida na spec; uma falha não deve perder o valor
 *                                  digitado, por isso NINGUÉM chama refresh() depois de um erro)
 */

const FILTER_TYPE_DEFAULTS = {
  clip: "ClipSegment",
  image: "ImageSegment",
  card: "CardSegment",
  video: "VideoOverlay",
  text: "TextOverlay",
  "image-overlay": "ImageOverlay",
  "progress-bar": "ProgressBar",
  track: "AudioTrack",
  music: "Music",
  captions: "Captions",
};

// Espelha os defaults do Pydantic (src/dmaker/domain/spec.py); usado só até GET /api/schema
// responder, e como fallback se a chamada falhar.
const FILTER_LOCAL_DEFAULTS = {"AudioSettings": {"music": null, "tracks": [], "voice_gain": 1.0, "normalize": "two-pass", "target_lufs": -14, "mute_clips": false}, "AudioTrack": {"volume": 1.0}, "CaptionStyle": {"mode": "karaoke", "font": null, "weight": "bold", "size": 72, "color": "white", "highlight_color": null, "outline_color": null, "outline": 5, "shadow": 2, "uppercase": true, "max_words": 4, "max_chars": 22, "y": null, "pop": false, "box_color": "#000000", "box_alpha": 0.6}, "Captions": {"source": "auto", "language": "pt", "model": "small", "device": "cpu", "vocabulary": [], "replacements": {}, "offset": 0.0, "enabled": true, "style": {"mode": "karaoke", "font": null, "weight": "bold", "size": 72.0, "color": "white", "highlight_color": null, "outline_color": null, "outline": 5.0, "shadow": 2.0, "uppercase": true, "max_words": 4, "max_chars": 22, "y": null, "pop": false, "box_color": "#000000", "box_alpha": 0.6}}, "CardSegment": {"label": null, "transition": null, "fade_in": 0.0, "fade_out": 0.0, "reframe": {"mode": "auto", "focus": [0.5, 0.5], "zoom": 1.0, "pad_color": "#000000", "blur": 28.0, "margin": 0.05, "radius": 0.018, "variant": null}, "color": {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0, "sharpen": 0.0, "denoise": false, "vignette": false, "lut": null, "extra": null}, "type": "card", "duration": 3.0, "subtitle": null, "variant": null, "logo": true, "background": null, "motion": "zoom-in", "motion_amount": 0.04}, "ClipSegment": {"label": null, "transition": null, "fade_in": 0.0, "fade_out": 0.0, "reframe": {"mode": "auto", "focus": [0.5, 0.5], "zoom": 1.0, "pad_color": "#000000", "blur": 28.0, "margin": 0.05, "radius": 0.018, "variant": null}, "color": {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0, "sharpen": 0.0, "denoise": false, "vignette": false, "lut": null, "extra": null}, "type": "clip", "src": null, "source": null, "start": 0.0, "end": null, "speed": 1.0, "volume": 1.0, "mute": false}, "ColorAdjust": {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0, "sharpen": 0.0, "denoise": false, "vignette": false, "lut": null, "extra": null}, "ImageOverlay": {"type": "image", "src": "logo", "position": "top-right", "width": 0.22, "margin": 40, "opacity": 1.0, "start": 0.0, "end": null, "fade": 0.3}, "ImageSegment": {"label": null, "transition": null, "fade_in": 0.0, "fade_out": 0.0, "reframe": {"mode": "auto", "focus": [0.5, 0.5], "zoom": 1.0, "pad_color": "#000000", "blur": 28.0, "margin": 0.05, "radius": 0.018, "variant": null}, "color": {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0, "sharpen": 0.0, "denoise": false, "vignette": false, "lut": null, "extra": null}, "type": "image", "duration": 3.0, "motion": "zoom-in", "motion_amount": 0.12}, "Music": {"volume": 0.18, "fade_in": 1.0, "fade_out": 2.0, "start_at": 0.0, "loop": true, "ducking": true, "duck_threshold": 0.02, "duck_ratio": 6, "duck_release": 350}, "Output": {"preset": "instagram/reels", "path": null, "fps": null, "encoder": "x264", "quality": "high", "thumbnail_at": null, "guides": false}, "ProgressBar": {"type": "progress-bar", "color": null, "height": 10, "position": "bottom", "track_alpha": 0.25}, "Reframe": {"mode": "auto", "focus": [0.5, 0.5], "zoom": 1.0, "pad_color": "#000000", "blur": 28.0, "margin": 0.05, "radius": 0.018, "variant": null}, "SourceRef": {"sync": 0.0, "audio_stream": 0, "label": null}, "TextOverlay": {"type": "text", "secondary": null, "role": "title", "start": 0.0, "end": null, "position": null, "x": null, "y": null, "animation": null, "style": {"font": null, "weight": null, "size": null, "color": null, "outline_color": null, "outline": null, "shadow": null, "box": null, "box_color": null, "box_alpha": null, "box_radius": null, "box_padding": null, "uppercase": null, "align": null, "max_width": null, "spacing": null}}, "TextStyle": {"font": null, "weight": null, "size": null, "color": null, "outline_color": null, "outline": null, "shadow": null, "box": null, "box_color": null, "box_alpha": null, "box_radius": null, "box_padding": null, "uppercase": null, "align": null, "max_width": null, "spacing": null}, "Transition": {"type": "fade", "duration": 0.5}, "VideoOverlay": {"type": "video", "src": null, "source": null, "start": 0.0, "end": null, "offset": 0.0, "position": "bottom-right", "x": null, "y": null, "width": 0.28, "aspect": null, "shape": "rounded", "radius": 0.08, "softness": 0.0, "border": 6, "border_color": "white", "shadow": true, "opacity": 1.0, "margin": 40, "volume": 1.0, "animation": "fade", "fade": 0.3}};

const ALIGN_OPTIONS = [
  { value: "left", label: "Esquerda" },
  { value: "center", label: "Centro" },
  { value: "right", label: "Direita" },
];

const DEVICE_OPTIONS = [
  { value: "cpu", label: "CPU" },
  { value: "cuda", label: "GPU (CUDA)" },
];

const FILTER_CATALOG = [
  { id: "reframe", label: "Reenquadrar", applies: ["clip", "image"], fields: [
    { path: "reframe.mode", label: "Modo", type: "select", options: "REFRAME_MODE_OPTIONS" },
    { path: "reframe.focus.0", label: "Foco X", type: "number", min: 0, max: 1, step: 0.05 },
    { path: "reframe.focus.1", label: "Foco Y", type: "number", min: 0, max: 1, step: 0.05 },
    { path: "reframe.zoom", label: "Zoom", type: "number", min: 1, max: 3, step: 0.05 },
    { path: "reframe.margin", label: "Margem", type: "number", min: 0, max: 0.3, step: 0.01 },
    { path: "reframe.radius", label: "Raio dos cantos", type: "number", min: 0, max: 0.2, step: 0.005 },
    { path: "reframe.variant", label: "Variante", type: "select", options: "VARIANT_OPTIONS" },
  ] },
  { id: "color", label: "Cor", applies: ["clip", "image"], fields: [
    { path: "color.brightness", label: "Brilho", type: "number", min: -1, max: 1, step: 0.05 },
    { path: "color.contrast", label: "Contraste", type: "number", min: 0, max: 3, step: 0.05 },
    { path: "color.saturation", label: "Saturação", type: "number", min: 0, max: 3, step: 0.05 },
    { path: "color.gamma", label: "Gama", type: "number", min: 0.1, max: 10, step: 0.1 },
    { path: "color.sharpen", label: "Nitidez", type: "number", min: 0, max: 2, step: 0.05 },
    { path: "color.denoise", label: "Reduzir ruído", type: "check" },
    { path: "color.vignette", label: "Vinheta", type: "check" },
    { path: "color.lut", label: "LUT (.cube)", type: "text" },
  ] },
  { id: "speed", label: "Velocidade", applies: ["clip"], fields: [
    { path: "speed", label: "Velocidade", type: "number", min: 0.1, max: 8, step: 0.1 },
  ] },
  { id: "clip-audio", label: "Áudio", applies: ["clip"], fields: [
    { path: "volume", label: "Volume", type: "number", min: 0, max: 4, step: 0.1 },
    { path: "mute", label: "Mudo", type: "check" },
  ] },
  { id: "fade", label: "Fade", applies: ["clip", "image", "card"], fields: [
    { path: "fade_in", label: "Fade in (s)", type: "number", min: 0, step: 0.1 },
    { path: "fade_out", label: "Fade out (s)", type: "number", min: 0, step: 0.1 },
  ] },
  { id: "transition", label: "Transição de entrada", applies: ["clip", "image", "card"], fields: [
    { path: "transition.type", label: "Tipo", type: "select", options: "TRANSITION_OPTIONS" },
    { path: "transition.duration", label: "Duração (s)", type: "number", min: 0.1, max: 5, step: 0.1 },
  ] },
  { id: "label", label: "Rótulo", applies: ["clip", "image", "card"], fields: [
    { path: "label", label: "Rótulo", type: "text" },
  ] },
  { id: "motion-image", label: "Movimento", applies: ["image"], fields: [
    { path: "motion", label: "Movimento", type: "select", options: "IMAGE_MOTION_OPTIONS" },
    { path: "motion_amount", label: "Intensidade", type: "number", min: 0, max: 0.6, step: 0.01 },
  ] },
  { id: "duration-image", label: "Duração", applies: ["image"], fields: [
    { path: "duration", label: "Duração (s)", type: "number", min: 0.1, step: 0.1 },
  ] },
  { id: "motion-card", label: "Movimento", applies: ["card"], fields: [
    { path: "motion", label: "Movimento", type: "select", options: "CARD_MOTION_OPTIONS" },
    { path: "motion_amount", label: "Intensidade", type: "number", min: 0, max: 0.3, step: 0.01 },
  ] },
  { id: "duration-card", label: "Duração", applies: ["card"], fields: [
    { path: "duration", label: "Duração (s)", type: "number", min: 0.1, step: 0.1 },
  ] },
  { id: "card-text", label: "Texto", applies: ["card"], fields: [
    { path: "title", label: "Título", type: "text" },
    { path: "subtitle", label: "Subtítulo", type: "text" },
  ] },
  { id: "card-style", label: "Estilo", applies: ["card"], fields: [
    { path: "variant", label: "Variante", type: "select", options: "VARIANT_OPTIONS" },
    { path: "logo", label: "Mostrar logo", type: "check" },
    { path: "background", label: "Fundo (cor ou imagem)", type: "text" },
  ] },
  { id: "pip-time", label: "Tempo", applies: ["video"], fields: [
    { path: "start", label: "Início (s)", type: "number", min: 0, step: 0.1 },
    { path: "end", label: "Fim (s)", type: "number", min: 0, step: 0.1 },
    { path: "offset", label: "Entrada na fonte (s)", type: "number", min: 0, step: 0.1 },
  ] },
  { id: "pip-position", label: "Posição", applies: ["video"], fields: [
    { path: "position", label: "Posição", type: "select", options: "IMAGE_OVERLAY_POSITION_OPTIONS" },
    { path: "x", label: "X (0 a 1)", type: "number", min: 0, max: 1, step: 0.01 },
    { path: "y", label: "Y (0 a 1)", type: "number", min: 0, max: 1, step: 0.01 },
    { path: "margin", label: "Margem (px)", type: "number", min: 0, step: 1 },
  ] },
  { id: "pip-size", label: "Tamanho", applies: ["video"], fields: [
    { path: "width", label: "Largura (fração)", type: "number", min: 0.01, max: 1, step: 0.01 },
    { path: "aspect", label: "Proporção (ex.: 16:9)", type: "text" },
  ] },
  { id: "pip-shape", label: "Forma", applies: ["video"], fields: [
    { path: "shape", label: "Formato", type: "select", options: "VIDEO_OVERLAY_SHAPE_OPTIONS" },
    { path: "radius", label: "Raio dos cantos", type: "number", min: 0, max: 0.5, step: 0.01 },
    { path: "softness", label: "Suavidade da borda (px)", type: "number", min: 0, step: 1 },
    { path: "border", label: "Borda (px)", type: "number", min: 0, step: 1 },
    { path: "border_color", label: "Cor da borda", type: "color" },
    { path: "shadow", label: "Sombra", type: "check" },
  ] },
  { id: "pip-opacity", label: "Opacidade", applies: ["video"], fields: [
    { path: "opacity", label: "Opacidade", type: "number", min: 0, max: 1, step: 0.05 },
  ] },
  { id: "pip-animation", label: "Animação", applies: ["video"], fields: [
    { path: "animation", label: "Animação", type: "select", options: "VIDEO_OVERLAY_ANIMATION_OPTIONS" },
    { path: "fade", label: "Duração da animação (s)", type: "number", min: 0, step: 0.05 },
  ] },
  { id: "pip-audio", label: "Áudio", applies: ["video"], fields: [
    { path: "volume", label: "Volume", type: "number", min: 0, max: 4, step: 0.1 },
  ] },
  { id: "text-content", label: "Texto", applies: ["text"], fields: [
    { path: "text", label: "Texto", type: "text" },
    { path: "secondary", label: "Segunda linha", type: "text" },
    { path: "role", label: "Papel", type: "select", options: "TEXT_ROLE_OPTIONS" },
  ] },
  { id: "text-time", label: "Tempo", applies: ["text"], fields: [
    { path: "start", label: "Início (s)", type: "number", min: 0, step: 0.1 },
    { path: "end", label: "Fim (s)", type: "number", min: 0, step: 0.1 },
  ] },
  { id: "text-position", label: "Posição", applies: ["text"], fields: [
    { path: "position", label: "Posição", type: "select", options: "TEXT_POSITION_OPTIONS" },
    { path: "x", label: "X (0 a 1)", type: "number", min: 0, max: 1, step: 0.01 },
    { path: "y", label: "Y (0 a 1)", type: "number", min: 0, max: 1, step: 0.01 },
  ] },
  { id: "text-animation", label: "Animação", applies: ["text"], fields: [
    { path: "animation", label: "Animação", type: "select", options: "TEXT_ANIMATION_OPTIONS" },
  ] },
  { id: "text-style", label: "Estilo", applies: ["text"], fields: [
    { path: "style.size", label: "Tamanho", type: "number", min: 1, step: 1 },
    { path: "style.color", label: "Cor", type: "color" },
    { path: "style.uppercase", label: "Maiúsculas", type: "check" },
    { path: "style.align", label: "Alinhamento", type: "select", options: "ALIGN_OPTIONS" },
    { path: "style.box", label: "Caixa de fundo", type: "check" },
    { path: "style.box_color", label: "Cor da caixa", type: "color" },
    { path: "style.box_alpha", label: "Opacidade da caixa", type: "number", min: 0, max: 1, step: 0.05 },
  ] },
  { id: "imgov-src", label: "Origem", applies: ["image-overlay"], fields: [
    { path: "src", label: "Arquivo", type: "src" },
  ] },
  { id: "imgov-time", label: "Tempo", applies: ["image-overlay"], fields: [
    { path: "start", label: "Início (s)", type: "number", min: 0, step: 0.1 },
    { path: "end", label: "Fim (s)", type: "number", min: 0, step: 0.1 },
  ] },
  { id: "imgov-position", label: "Posição", applies: ["image-overlay"], fields: [
    { path: "position", label: "Posição", type: "select", options: "IMAGE_OVERLAY_POSITION_OPTIONS" },
  ] },
  { id: "imgov-size", label: "Tamanho", applies: ["image-overlay"], fields: [
    { path: "width", label: "Largura (fração)", type: "number", min: 0.01, max: 1, step: 0.01 },
  ] },
  { id: "imgov-opacity-fade", label: "Opacidade/Fade", applies: ["image-overlay"], fields: [
    { path: "opacity", label: "Opacidade", type: "number", min: 0, max: 1, step: 0.05 },
    { path: "fade", label: "Duração do fade (s)", type: "number", min: 0, step: 0.05 },
  ] },
  { id: "progress", label: "Barra de progresso", applies: ["progress-bar"], fields: [
    { path: "color", label: "Cor (vazio = tema)", type: "color" },
    { path: "height", label: "Altura (px)", type: "number", min: 1, step: 1 },
    { path: "position", label: "Posição", type: "select", options: "PROGRESS_POSITION_OPTIONS" },
    { path: "track_alpha", label: "Opacidade da trilha", type: "number", min: 0, max: 1, step: 0.05 },
  ] },
  { id: "track-volume", label: "Faixa de áudio", applies: ["track"], fields: [
    { path: "volume", label: "Volume", type: "number", min: 0, max: 4, step: 0.1 },
  ] },
  { id: "music-main", label: "Música", applies: ["music"], fields: [
    { path: "src", label: "Arquivo", type: "src" },
    { path: "volume", label: "Volume", type: "number", min: 0, max: 2, step: 0.01 },
    { path: "start_at", label: "Começar em (s)", type: "number", min: 0, step: 0.1 },
    { path: "loop", label: "Repetir em loop", type: "check" },
    { path: "ducking", label: "Abaixar sob a voz (ducking)", type: "check" },
    { path: "duck_threshold", label: "Limiar do ducking", type: "number", min: 0, max: 1, step: 0.01 },
    { path: "duck_ratio", label: "Razão do ducking", type: "number", min: 1, max: 20, step: 0.5 },
    { path: "duck_release", label: "Release do ducking (ms)", type: "number", min: 10, max: 5000, step: 10 },
  ] },
  { id: "music-fade", label: "Fade", applies: ["music"], fields: [
    { path: "fade_in", label: "Fade in (s)", type: "number", min: 0, step: 0.1 },
    { path: "fade_out", label: "Fade out (s)", type: "number", min: 0, step: 0.1 },
  ] },
  { id: "captions-main", label: "Legendas", applies: ["captions"], fields: [
    { path: "source", label: "Origem (auto ou .srt)", type: "src" },
    { path: "language", label: "Idioma", type: "text" },
    { path: "model", label: "Modelo", type: "select", options: "MODEL_OPTIONS" },
    { path: "device", label: "Dispositivo", type: "select", options: "DEVICE_OPTIONS" },
    { path: "offset", label: "Deslocamento (s)", type: "number", step: 0.05 },
  ] },
  { id: "captions-style", label: "Estilo", applies: ["captions"], fields: [
    { path: "style.mode", label: "Estilo", type: "select", options: "CAPTION_STYLE_MODE_OPTIONS" },
    { path: "style.size", label: "Tamanho", type: "number", min: 1, step: 1 },
    { path: "style.color", label: "Cor", type: "color" },
    { path: "style.uppercase", label: "Maiúsculas", type: "check" },
    { path: "style.max_words", label: "Máx. palavras por linha", type: "number", min: 1, max: 12, step: 1 },
    { path: "style.max_chars", label: "Máx. caracteres por linha", type: "number", min: 4, max: 80, step: 1 },
    { path: "style.box_color", label: "Cor da caixa", type: "color" },
    { path: "style.box_alpha", label: "Opacidade da caixa", type: "number", min: 0, max: 1, step: 0.05 },
    { path: "style.y", label: "Posição Y (0 a 1)", type: "number", min: 0, max: 1, step: 0.01 },
  ] },
  { id: "project-output", label: "Saída", applies: ["project"], base: "output", defaultsType: "Output", fields: [
    { path: "preset", label: "Preset", type: "preset-select" },
    { path: "quality", label: "Qualidade", type: "select", options: "QUALITY_OPTIONS" },
    { path: "encoder", label: "Encoder", type: "select", options: "ENCODER_OPTIONS" },
    { path: "fps", label: "FPS (opcional)", type: "number", min: 1, max: 120, step: 1 },
    { path: "guides", label: "Mostrar guias de zona segura", type: "check" },
  ] },
  { id: "project-audio", label: "Áudio geral", applies: ["project"], base: "audio", defaultsType: "AudioSettings", fields: [
    { path: "voice_gain", label: "Ganho da voz", type: "number", min: 0, max: 4, step: 0.1 },
    { path: "normalize", label: "Normalização", type: "select", options: "NORMALIZE_OPTIONS" },
    { path: "target_lufs", label: "LUFS alvo", type: "number", min: -30, max: -5, step: 0.5 },
    { path: "mute_clips", label: "Silenciar áudio original dos clipes", type: "check" },
  ] },
];

let filterSchemaCache = null;
let filterSchemaPromise = null;

function loadFilterSchema() {
  if (filterSchemaCache || filterSchemaPromise) return filterSchemaPromise;
  filterSchemaPromise = api.get("/api/schema").then((s) => { filterSchemaCache = s; return s; }).catch(() => null);
  return filterSchemaPromise;
}

/** Objeto de defaults completo (aninhado) do tipo `typeName`, na forma de um item da spec
 * (ex.: defaultsFor("ClipSegment").reframe.mode). Schema quando já carregado, senão a tabela local. */
function defaultsFor(typeName) {
  const fromSchema = filterSchemaCache && filterSchemaCache.$defs && filterSchemaCache.$defs[typeName];
  if (fromSchema) {
    const out = {};
    for (const [field, prop] of Object.entries(fromSchema.properties || {})) {
      if ("default" in prop) out[field] = prop.default;
    }
    return out;
  }
  return FILTER_LOCAL_DEFAULTS[typeName] || {};
}

// `const` de topo de arquivo não vira propriedade de `window` (diferente de `var`), então um
// campo do catálogo que referencia uma lista pelo nome (ex.: options: "VARIANT_OPTIONS") só
// consegue achá-la aqui, num mapa explícito, não em `window[nome]`.
const SHARED_OPTION_SETS = {
  REFRAME_MODE_OPTIONS,
  VARIANT_OPTIONS,
  TRANSITION_OPTIONS,
  IMAGE_MOTION_OPTIONS,
  CARD_MOTION_OPTIONS,
  TEXT_ROLE_OPTIONS,
  TEXT_POSITION_OPTIONS,
  TEXT_ANIMATION_OPTIONS,
  IMAGE_OVERLAY_POSITION_OPTIONS,
  PROGRESS_POSITION_OPTIONS,
  VIDEO_OVERLAY_SHAPE_OPTIONS,
  VIDEO_OVERLAY_ANIMATION_OPTIONS,
  MODEL_OPTIONS,
  CAPTION_STYLE_MODE_OPTIONS,
  NORMALIZE_OPTIONS,
  QUALITY_OPTIONS,
  ENCODER_OPTIONS,
  ALIGN_OPTIONS,
  DEVICE_OPTIONS,
};

function resolveOptions(options) {
  if (Array.isArray(options)) return options;
  return SHARED_OPTION_SETS[options] || [];
}

function fEsc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function valuesEqual(a, b) {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

function groupsFor(typeKey) {
  return FILTER_CATALOG.filter((g) => g.applies.includes(typeKey));
}

function createFilters(container, { applyOp, getSpec }) {
  let selection = { typeKey: null, base: null };
  let visibleGroups = new Set();
  let lastSelectionKey = null;
  const debounceTimers = new Map();

  loadFilterSchema().then(() => render());

  function fieldFullPath(group, field) {
    return `${group.base ?? selection.base}.${field.path}`;
  }

  function fieldDefaultsType(group) {
    return group.defaultsType || FILTER_TYPE_DEFAULTS[selection.typeKey];
  }

  function fieldCurrentValue(group, field) {
    const spec = getSpec();
    const base = group.base ?? selection.base;
    const raw = getPath(spec, `${base}.${field.path}`);
    if (raw !== undefined) return raw;
    return getPath(defaultsFor(fieldDefaultsType(group)), field.path);
  }

  function fieldDefaultValue(group, field) {
    return getPath(defaultsFor(fieldDefaultsType(group)), field.path);
  }

  function isGroupApplied(group) {
    return group.fields.some((f) => !valuesEqual(fieldCurrentValue(group, f), fieldDefaultValue(group, f)));
  }

  function fieldHtml(group, field) {
    const path = fieldFullPath(group, field);
    const value = fieldCurrentValue(group, field);
    if (field.type === "select") {
      return selectField(path, field.label, value ?? "", resolveOptions(field.options));
    }
    if (field.type === "check") {
      return checkField(path, field.label, !!value);
    }
    if (field.type === "color") {
      return textField(path, field.label, value ?? "");
    }
    if (field.type === "src") {
      const browseKind = group.id === "imgov-src" ? "image" : group.id === "music-main" ? "audio" : "video";
      return srcField(path, field.label, value ?? "", browseKind);
    }
    if (field.type === "preset-select") {
      const options = (state.stateInfo?.presets || []).map((p) => ({ value: p.id, label: `${p.platform} · ${p.name} (${p.id})` }));
      return selectField(path, field.label, value ?? "", options.length ? options : [{ value: value ?? "", label: value ?? "" }]);
    }
    if (field.type === "text") {
      return textField(path, field.label, value ?? "");
    }
    return numField(path, field.label, value, { min: field.min, max: field.max, step: field.step });
  }

  function groupHtml(group, applied) {
    return `
      <div class="filter-group" data-group-id="${fEsc(group.id)}">
        <div class="filter-group-header">
          <span>${fEsc(group.label)}</span>
          <button type="button" class="icon-btn filter-remove" data-remove-group="${fEsc(group.id)}" title="Remover">&times;</button>
        </div>
        <div class="form-grid">${group.fields.map((f) => fieldHtml(group, f)).join("")}</div>
      </div>`;
  }

  function selectionTitle() {
    if (!selection.typeKey) return "Projeto (nada selecionado)";
    const names = {
      clip: "Clipe", image: "Imagem", card: "Cartão", video: "Vídeo (PiP)", text: "Texto",
      "image-overlay": "Imagem (sobreposição)", "progress-bar": "Barra de progresso",
      track: "Faixa de áudio", music: "Música", captions: "Legendas",
    };
    return names[selection.typeKey] || selection.typeKey;
  }

  function render() {
    const typeKey = selection.typeKey || "project";
    const all = groupsFor(typeKey);
    const applied = all.filter((g) => visibleGroups.has(g.id) || isGroupApplied(g));
    const available = all.filter((g) => !applied.includes(g));
    container.innerHTML = `
      <div class="filters-title">${fEsc(selectionTitle())}</div>
      <div id="filters-applied">${applied.map((g) => groupHtml(g, true)).join("") || '<p class="empty-hint">Nenhum filtro aplicado.</p>'}</div>`;
    // o botão "+" e o menu ficam fora de #filters-body (no cabeçalho do painel, index.html), dentro
    // do mesmo .dropdown que o resto da interface usa: assim o fechamento ao clicar fora
    // (closeDropdowns, em app.js) enxerga o botão como parte do dropdown e não fecha o menu na hora
    // de abrir. Só o conteúdo do menu é responsabilidade daqui.
    const menu = document.getElementById("filters-add-menu");
    if (menu) {
      menu.innerHTML = available.map((g) => `<button type="button" data-add-group="${fEsc(g.id)}">${fEsc(g.label)}</button>`).join("")
        || '<button type="button" disabled>Nada mais para adicionar</button>';
    }
  }

  function commitField(fullPath, value) {
    applyOp({ type: "set_field", path: fullPath, value });
  }

  /** Edita um campo possivelmente aninhado (ex.: "reframe.mode"): se o contêiner do primeiro nível
   * (ex.: "reframe", "transition", "style") ainda não existir na spec (objeto opcional nulo, como
   * uma transição ainda não criada), começa por uma cópia dos defaults antes de aplicar o campo,
   * e manda o contêiner inteiro num só set_field. Uniforme para todo grupo, sem caso especial. */
  function applyFieldEdit(group, field, rawValue) {
    const base = group.base ?? selection.base;
    const segs = field.path.split(".");
    if (segs.length === 1) {
      commitField(`${base}.${field.path}`, rawValue);
      return;
    }
    const containerKey = segs[0];
    const rest = segs.slice(1).join(".");
    const containerPath = `${base}.${containerKey}`;
    const current = getPath(getSpec(), containerPath);
    const container = current && typeof current === "object" && !Array.isArray(current)
      ? JSON.parse(JSON.stringify(current))
      : JSON.parse(JSON.stringify(defaultsFor(fieldDefaultsType(group))[containerKey] || {}));
    setPath(container, rest, rawValue);
    commitField(containerPath, container);
  }

  function findGroupAndField(path) {
    for (const group of groupsFor(selection.typeKey || "project")) {
      for (const field of group.fields) {
        if (fieldFullPath(group, field) === path) return { group, field };
      }
    }
    return null;
  }

  function debouncedEdit(group, field, rawValue) {
    const key = fieldFullPath(group, field);
    clearTimeout(debounceTimers.get(key));
    debounceTimers.set(key, setTimeout(() => applyFieldEdit(group, field, rawValue), 300));
  }

  container.addEventListener("input", (e) => {
    const el = e.target;
    if (!el.matches('input[type="text"][data-path], input[type="number"][data-path], textarea[data-path]')) return;
    const found = findGroupAndField(el.dataset.path);
    if (!found) return;
    const raw = el.dataset.kind === "number" ? (el.value === "" ? undefined : Number(el.value)) : (el.value === "" ? undefined : el.value);
    debouncedEdit(found.group, found.field, raw);
  });

  container.addEventListener("change", (e) => {
    const el = e.target;
    if (el.matches("[data-browse-path]")) return;
    if (!el.matches("select[data-path], input[type=checkbox][data-path]")) return;
    const found = findGroupAndField(el.dataset.path);
    if (!found) return;
    const raw = el.dataset.kind === "boolean" ? el.checked : (el.value === "" ? undefined : el.value);
    clearTimeout(debounceTimers.get(el.dataset.path));
    applyFieldEdit(found.group, found.field, raw);
  });

  container.addEventListener("click", (e) => {
    const browseBtn = e.target.closest("[data-browse-path]");
    if (browseBtn) {
      const found = findGroupAndField(browseBtn.dataset.browsePath);
      if (found) {
        openFileBrowser({
          multi: false,
          onSelect: (paths) => { closeModal(); applyFieldEdit(found.group, found.field, paths[0]); },
        });
      }
      return;
    }
    const removeBtn = e.target.closest("[data-remove-group]");
    if (removeBtn) {
      const group = FILTER_CATALOG.find((g) => g.id === removeBtn.dataset.removeGroup);
      if (!group) return;
      visibleGroups.delete(group.id);
      const containers = new Set(group.fields.map((f) => f.path.split(".")[0]));
      const base = group.base ?? selection.base;
      (async () => {
        for (const key of containers) await applyOp({ type: "set_field", path: `${base}.${key}`, value: null });
        render();
      })();
      return;
    }
  });

  // O botão e o menu do "+" ficam no cabeçalho do painel (index.html), fora de `container`, dentro
  // do mesmo .dropdown que app.js já sabe abrir/fechar (toggleDropdown/closeDropdowns, ligado a um
  // clique fora de qualquer .dropdown): reaproveita esse mecanismo em vez de duplicar.
  document.getElementById("btn-add-filter").addEventListener("click", () => toggleDropdown("filters-add-menu"));
  document.getElementById("filters-add-dropdown").addEventListener("click", (e) => {
    const addBtn = e.target.closest("[data-add-group]");
    if (!addBtn) return;
    visibleGroups.add(addBtn.dataset.addGroup);
    closeDropdowns();
    render();
  });

  return {
    setSelection(typeKey, base) {
      selection = { typeKey: typeKey || null, base: base || null };
      const key = `${typeKey}:${base}`;
      if (key !== lastSelectionKey) visibleGroups = new Set();
      lastSelectionKey = key;
      render();
    },
    refresh() {
      render();
    },
  };
}

window.DMakerFilters = { FILTER_CATALOG, create: createFilters };

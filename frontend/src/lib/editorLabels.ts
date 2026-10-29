/* Os rótulos em português dos valores das listas da spec. Os VALORES vêm do schema (`editorSchema.ts`); aqui só
   fica o texto bonito de cada um. Valor que o schema ganhar e não estiver aqui aparece com o próprio valor, então
   nada some do formulário por falta de rótulo. A chave é "Definição.campo", como no `$defs` do schema. */

export interface OptionItem {
  value: string
  label: string
}

const POSITIONS_9: Record<string, string> = {
  'top-left': 'Topo esquerda',
  'top-right': 'Topo direita',
  'bottom-left': 'Base esquerda',
  'bottom-right': 'Base direita',
  top: 'Topo',
  bottom: 'Base',
  center: 'Centro',
}

const LABELS: Record<string, Record<string, string>> = {
  'Output.quality': { max: 'Máxima (mais lenta)', high: 'Alta', medium: 'Média', draft: 'Rascunho' },
  'Output.encoder': {
    x264: 'x264 (CPU)',
    auto: 'Automático (placa de vídeo, se houver)',
    nvenc: 'NVENC (Nvidia)',
    amf: 'AMF (AMD)',
    qsv: 'QSV (Intel)',
  },
  'Reframe.mode': {
    auto: 'Automático',
    crop: 'Cortar',
    pad: 'Preencher com barras',
    blur: 'Fundo desfocado',
    brand: 'Fundo da marca',
    stretch: 'Esticar',
  },
  'ImageSegment.motion': {
    none: 'Nenhum',
    'zoom-in': 'Zoom in',
    'zoom-out': 'Zoom out',
    'pan-left': 'Pan esquerda',
    'pan-right': 'Pan direita',
  },
  'CardSegment.motion': { none: 'Nenhum', 'zoom-in': 'Zoom in' },
  'CardSegment.variant': { light: 'Claro', dark: 'Escuro' },
  'TextOverlay.role': {
    hook: 'Gancho',
    title: 'Título',
    subtitle: 'Subtítulo',
    cta: 'Chamada para ação',
    'lower-third': 'Legenda inferior',
    custom: 'Personalizado',
  },
  'TextOverlay.position': { top: 'Topo', center: 'Centro', bottom: 'Base' },
  'TextOverlay.animation': {
    none: 'Nenhuma',
    fade: 'Fade',
    pop: 'Pop',
    'slide-up': 'Slide para cima',
    typewriter: 'Máquina de escrever',
  },
  'ImageOverlay.position': POSITIONS_9,
  'VideoOverlay.position': POSITIONS_9,
  'ProgressBar.position': { top: 'Topo', bottom: 'Base' },
  'VideoOverlay.shape': { rect: 'Retângulo', rounded: 'Cantos arredondados', circle: 'Círculo' },
  'VideoOverlay.animation': { none: 'Nenhuma', fade: 'Fade', slide: 'Slide' },
  'CaptionStyle.mode': { karaoke: 'Karaokê', classic: 'Clássico', boxed: 'Caixa', rounded: 'Caixa arredondada' },
  'AudioSettings.normalize': { 'two-pass': 'Duas passadas', fast: 'Rápida', off: 'Desligada' },
  // o schema não lista os tipos de transição (são validados pelo catálogo): estes são os rótulos dos mais usados
  'Transition.type': {
    cut: 'Corte seco',
    fade: 'Fade',
    dissolve: 'Dissolve',
    wipeleft: 'Wipe esquerda',
    wiperight: 'Wipe direita',
    wipeup: 'Wipe cima',
    wipedown: 'Wipe baixo',
    slideleft: 'Slide esquerda',
    slideright: 'Slide direita',
    slideup: 'Slide cima',
    slidedown: 'Slide baixo',
    smoothleft: 'Smooth esquerda',
    circleopen: 'Círculo abrindo',
    zoomin: 'Zoom in',
    fadeblack: 'Fade para preto',
    fadewhite: 'Fade para branco',
    pixelize: 'Pixelizar',
  },
  // o schema de `Captions.model` é texto livre (o Whisper aceita mais nomes): estes são os modelos de sempre
  'Captions.model': { tiny: 'Tiny', base: 'Base', small: 'Small', medium: 'Medium', 'large-v3': 'Large v3' },
}

/** Os valores de `Captions.model` quando o schema não os lista, do menor ao maior. */
export const CAPTION_MODEL_VALUES = ['tiny', 'base', 'small', 'medium', 'large-v3']

/** Sincronização da fonte: o schema aceita "auto" ou um número, então o formulário trabalha com dois modos. */
export const SYNC_MODE_LABEL = { auto: 'Automática (pelo áudio)', manual: 'Manual (segundos)' } as const

/** Origens de imagem sobreposta que não são arquivo: o logo da marca em quatro variantes. */
export const LOGO_SOURCES: OptionItem[] = [
  { value: 'logo', label: 'Logo horizontal' },
  { value: 'logo:symbol', label: 'Logo símbolo' },
  { value: 'logo:horizontal_dark', label: 'Logo horizontal (escuro)' },
  { value: 'logo:symbol_dark', label: 'Logo símbolo (escuro)' },
]

/**
 * As transições da lista: "corte seco" primeiro e depois as do catálogo do servidor. Sem catálogo (a consulta
 * falhou), as de sempre, para o campo nunca ficar vazio.
 */
export function transitionItems(catalogNames: string[]): OptionItem[] {
  const names = catalogNames.length ? catalogNames : Object.keys(LABELS['Transition.type'] ?? {})
  return optionItems('Transition.type', ['cut', ...names.filter((name) => name !== 'cut')])
}

/** O rótulo de um valor; sem rótulo conhecido, o próprio valor. */
export function optionLabel(key: string, value: string): string {
  return LABELS[key]?.[value] ?? value
}

/** As opções de uma lista, na ordem em que o schema as dá (ou na dos `values` pedidos). */
export function optionItems(key: string, values: string[]): OptionItem[] {
  return values.map((value) => ({ value, label: optionLabel(key, value) }))
}

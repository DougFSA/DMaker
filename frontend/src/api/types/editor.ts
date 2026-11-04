/* Tipos das rotas do editor (src/dmaker/ui/server.py): salvar a spec, legendas, linha do tempo, edição por
   operação, tema, proxies, sondagem de mídia, forma de onda, sincronização, conferência do vídeo e layouts. */
import type { JobSnapshot } from '../types'
import type { AudioEffectSettings } from './audioEffects'

/** A spec do projeto como o servidor a aceita (PUT /api/projects/{nome}); a validação completa é do backend. */
export type SpecDocument = Record<string, unknown>

/** PUT /api/projects/{nome}. */
export interface SaveProjectResponse {
  ok: boolean
  spec_path: string
  /** A revisão do `spec.json` depois da gravação; servidor antigo não manda. */
  revision?: string
}

/** GET /api/projects/{nome}/revision: a revisão do `spec.json` no disco, leve para consultar a cada poucos segundos. */
export interface RevisionResponse {
  revision: string
}

/** O corpo do 409 de PUT /api/projects/{nome} com `If-Match`: o disco mudou desde a última leitura. */
export interface SaveConflictBody {
  detail?: string
  /** A revisão que está no disco agora; nula se o projeto deixou de existir. */
  revision: string | null
}

/* ---------- legendas automáticas ---------- */

export interface CaptionWord {
  start: number
  end: number
  text: string
  /** Confiança do modelo (0 a 1); ausente em legenda que não veio do Whisper. */
  probability?: number | null
}

export interface CaptionCue {
  start: number
  end: number
  text: string
  words?: CaptionWord[]
}

/** GET /api/projects/{nome}/captions: o arquivo captions.auto.json do projeto. */
export interface CaptionsDocument {
  language: string
  cues: CaptionCue[]
  [extra: string]: unknown
}

/** PUT /api/projects/{nome}/captions. */
export interface CaptionsSaved {
  ok: boolean
  cues: number
}

/* ---------- linha do tempo ---------- */

export type TrackKind = 'video' | 'audio' | 'text' | 'graphics' | 'captions' | 'markers'

/** Um item de uma trilha da vista (trecho, sobreposição, faixa de áudio, narração, música, legenda ou marcador). */
export interface TimelineItem {
  id: string
  kind: string
  /** Posição de origem do item: em `timeline`, `overlays`, `audio.tracks` ou `markers`. */
  index: number
  label: string
  start: number
  end: number
  in_point: number
  out_point: number | null
  src: string | null
  source: string | null
  transition: Record<string, unknown> | null
  muted: boolean
  /** Detalhes que dependem do tipo (velocidade, posição, pedaços de fonte com `parts`, narração estimada). */
  extra: Record<string, unknown>
  /** Caminho absoluto resolvido pelo servidor; nulo em cartão, texto e logo. */
  path: string | null
  /** O arquivo do item não está no disco: o item abre marcado "fonte não encontrada". */
  missing?: boolean
}

export interface TimelineTrack {
  id: string
  kind: TrackKind
  label: string
  muted: boolean
  hidden: boolean
  locked: boolean
  /** Controles de mixagem salvos em `tracks` (só as trilhas de áudio os usam): ganho em dB, pan de -1 a 1 e solo. */
  gain_db?: number
  pan?: number
  solo?: boolean
  /** A trilha não soa: está muda, ou outra trilha de áudio está em solo. */
  silenced?: boolean
  items: TimelineItem[]
}

/** Uma fonte sincronizada na vista, com o caminho já resolvido. */
export interface TimelineSource {
  src: string
  parts: string[]
  offset: number
  in_point: number
  path: string
  /** Algum arquivo da fonte não está no disco. */
  missing?: boolean
}

/** POST /api/projects/{nome}/timeline e o campo `timeline` da resposta de editar. */
export interface TimelineView {
  total: number
  fps: number
  width: number
  height: number
  tracks: TimelineTrack[]
  sources: Record<string, TimelineSource>
  warnings: string[]
}

/* ---------- caixas das sobreposições ---------- */

/** O tipo da sobreposição de uma caixa: `progress-bar` e `audiogram` têm área mas não se movem. */
export type BoxKind = 'text' | 'image' | 'video' | 'html' | 'progress-bar' | 'audiogram'

/** De onde vem o lugar da sobreposição: `xy` (campos `x`/`y`), `position` (nomeada), `region`, `anchor` (HTML presa a
 * uma palavra da legenda) ou `full` (HTML no quadro todo). */
export type BoxPlacement = 'xy' | 'position' | 'region' | 'anchor' | 'full'

/** Como a caixa se redimensiona: pela largura da quebra (texto), mantendo o aspecto (imagem, PiP), livre (HTML) ou não. */
export type BoxResize = 'text_width' | 'keep_aspect' | 'free' | 'none'

export type SafeZoneSide = 'top' | 'bottom' | 'left' | 'right'

/** A caixa de uma sobreposição no quadro nativo do preset. Medidas em fração do quadro; ficam nulas onde o servidor
 * não sabe o lugar (HTML presa a palavra, mídia sumida, modelo inválido), e então `movable` é falso. */
export interface OverlayBox {
  /** O índice da sobreposição em `spec.overlays`. */
  index: number
  kind: BoxKind
  start: number
  /** Nulo quando a sobreposição vai até o fim do vídeo. */
  end: number | null
  left: number | null
  top: number | null
  width: number | null
  height: number | null
  /** O ponto que o `x`/`y` da spec representa (o centro, ou a borda no texto alinhado à esquerda ou à direita). */
  anchor: { x: number; y: number } | null
  placement: BoxPlacement
  region: string | null
  resize: BoxResize
  /** Só no texto: a área da quebra (`style.max_width`), com o preenchimento das duas pontas. */
  wrap: { left: number; width: number } | null
  movable: boolean
  locked_reason: string | null
  /** Os lados em que a caixa invade a zona segura (com 1 px de folga). */
  outside_safe_zone: SafeZoneSide[]
}

/** As margens da zona segura do preset em fração do quadro (`top` e `bottom` sobre a altura, o resto sobre a largura). */
export interface SafeZoneFractions {
  top: number
  bottom: number
  left: number
  right: number
}

/** POST /api/projects/{nome}/boxes: a conta única do render, do QA da zona segura e do palco. */
export interface BoxLayout {
  /** A resolução nativa do preset do projeto. */
  width: number
  height: number
  safe_zone: SafeZoneFractions
  /** Na ordem de `spec.overlays`. */
  boxes: OverlayBox[]
}

/* ---------- o quadro real de um instante ---------- */

/** Onde o quadro pedido está: pronto, sendo feito, com erro, ou superado por um pedido mais novo do mesmo projeto. */
export type InstantFrameState = 'ready' | 'pending' | 'error' | 'superseded'

/** POST /api/projects/{nome}/frame e GET .../frame/{chave}: um quadro renderizado pelo pipeline de verdade. */
export interface InstantFrame {
  key: string
  status: InstantFrameState
  /** O instante exato que o quadro mostra (já na grade de quadros do vídeo): é ele que a tela mostra, não o pedido. */
  t: number | null
  /** O que o quadro não mostra (uma legenda automática sem transcrição em cache, por exemplo). */
  notes: string[]
  /** Só em `ready`: o endereço da imagem. */
  url?: string
  /** Só em `error`: a mensagem em português. */
  error?: string
  /** Só em `pending`: a etapa em andamento e o percentual dela. */
  label?: string
  percent?: number
}

/** As operações de POST /api/projects/{nome}/edit que a interface usa: as da linha do tempo, as de marcador e as de
 * edição de onda (`audio_*`, `track_set`). Os tempos das `audio_*` são da linha do tempo do projeto. */
export type EditOperation =
  | { type: 'split'; index: number; at: number }
  | { type: 'remove'; index: number }
  | { type: 'move'; index: number; to: number }
  | { type: 'trim'; index: number; side: 'in' | 'out'; delta: number }
  | { type: 'duplicate'; index: number }
  | { type: 'insert'; index: number; segment: Record<string, unknown> }
  | { type: 'overlay_span'; index: number; start: number; end?: number | null }
  | { type: 'overlay_remove'; index: number }
  | { type: 'overlay_duplicate'; index: number }
  | { type: 'set_field'; path: string; value: unknown }
  | { type: 'marker_add'; at?: number; start?: number; end?: number; text?: string; color?: string; group?: string }
  | {
      type: 'marker_set'
      index: number
      at?: number
      start?: number
      end?: number
      text?: string
      color?: string | null
      group?: string
    }
  | { type: 'marker_remove'; index: number }
  | {
      type: 'audio_effect'
      action: 'add' | 'remove' | 'move' | 'enable' | 'disable' | 'set'
      target: string
      /** O efeito novo (`add`), com o intervalo em tempo do item. */
      effect?: AudioEffectSettings
      index?: number
      to?: number
      params?: Record<string, unknown>
    }
  | { type: 'audio_silence'; target: string; start: number; end: number }
  | { type: 'audio_cut'; target: string; start: number; end: number }
  | { type: 'audio_split'; target: string; at: number }
  | { type: 'audio_envelope'; target: string; points: Array<{ at: number; db: number }> }
  /** O Fade In (`in`) ou Fade Out (`out`) preso à borda do item; duração 0 tira o fade e sem `curve` mantém a que ele tinha. */
  | { type: 'audio_fade'; target: string; side: 'in' | 'out'; duration: number; curve?: string }
  /** O crossfade de trilhas: um Fade Ajustável de saída num item e de entrada no outro, no mesmo intervalo da linha do tempo. */
  | {
      type: 'audio_crossfade_tracks'
      out_target: string
      in_target: string
      start: number
      end: number
      kind?: 'constant_gain' | 'constant_power_1' | 'constant_power_2' | 'custom'
      curve?: string
      mid_adjust?: number
    }
  /** O crossfade do som no corte entre o clipe `index - 1` e o `index` (J-cut e L-cut); `duration` 0 tira. */
  | { type: 'audio_crossfade_clips'; index: number; duration: number; curve?: string }
  | { type: 'track_set'; track: string; gain_db?: number; pan?: number; solo?: boolean; muted?: boolean; hidden?: boolean; locked?: boolean }
  /** Guarda o trecho que só tem chiado como perfil; sem `start` e `end`, é o trecho mais quieto do item. Os tempos são
   *  segundos da linha do tempo. */
  | { type: 'noise_profile_set'; name: string; target: string; start?: number; end?: number }
  | { type: 'noise_profile_remove'; name: string }

export interface EditResponse {
  spec: SpecDocument
  timeline: TimelineView
  /** Os marcadores que a edição apagou por estarem num trecho cortado (um aviso por marcador). */
  edit_warnings?: string[]
  /** O que a operação fez, para mostrar (quantos silêncios foram truncados). */
  edit_notes?: string[]
}

/** O nível do ruído de um perfil por banda de um terço de oitava (POST /api/projects/{nome}/noise-profile). */
export interface NoiseProfileReport {
  name: string
  target: string
  start: number
  end: number
  duration: number
  /** O nível do trecho inteiro, em dBFS. */
  level_db: number
  bands: Array<{ hz: number; db: number }>
}

/** Pedido de POST /api/projects/{nome}/audio-effect-action. */
export interface EffectActionRequest {
  effect: string
  action: string
  /** O item de onde sai o trecho (`audio.voiceover.0`). */
  target: string
  /** Um perfil de ruído do projeto, ou `auto` (o trecho mais quieto do item). */
  profile?: string
}

/** Pedido de POST /api/projects/{nome}/effect-compare: um trecho do item com o efeito desligado e ligado. */
export interface EffectCompareRequest {
  target: string
  /** A posição do efeito na cadeia do item. */
  index: number
  /** Segundos da linha do tempo onde o trecho começa (o cursor); o item começa em 0 sem ele. */
  at?: number | null
  duration: number
}

export interface EffectCompareResponse {
  before_url: string
  after_url: string
  duration_s: number
}

/* ---------- tema e cartões ---------- */

/** GET /api/projects/{nome}/theme: o que o player precisa para desenhar texto e logo como o render. */
export interface ProjectTheme {
  colors: Record<string, string>
  font: string
  logos: Record<string, string | null>
  no_dash: boolean
}

/** Campos do cartão para GET /api/card-preview (PNG); só `title` é obrigatório. */
export interface CardPreviewParams {
  title: string
  brand?: string | null
  preset?: string
  subtitle?: string | null
  variant?: string | null
  logo?: boolean
  background?: string | null
  width?: number
}

/* ---------- proxies de prévia ---------- */

export interface ProxyEntry {
  src: string
  /** Onde o proxy fica; nulo quando o original sumiu do disco (não há o que gerar). */
  proxy: string | null
  ready: boolean
  /** O vídeo original não está no disco. */
  missing?: boolean
  url: string | null
}

/** POST /api/projects/{nome}/proxies: `job` é o snapshot do job que gera os que faltam (nulo se já estão prontos). */
export interface ProxiesBuild {
  job: JobSnapshot | null
  proxies: ProxyEntry[]
}

/* ---------- áudio da prévia ---------- */

/** Em que pé está a mixagem de áudio de uma versão da spec: pronta (com a URL), sendo feita ou falhou. */
export type PreviewAudioState = 'ready' | 'building' | 'failed'

/** POST e GET /api/projects/{nome}/preview-audio. */
export interface PreviewAudioStatus {
  state: PreviewAudioState
  /** Identifica a parte de áudio da spec: a mesma chave é a mesma mixagem. */
  key: string
  url: string | null
  duration_s: number | null
  /** O que ficou fora da mixagem (uma narração ainda não sintetizada, por exemplo). */
  warnings: string[]
  error: string | null
  /** A etapa em andamento e o percentual do comando atual. */
  label: string
  percent: number
}

/* ---------- sondagem, forma de onda e sincronização ---------- */

export type ProbeKind = 'image' | 'video' | 'audio'

/** Um arquivo sondado por POST /api/probe; os que falham voltam só com `error`. */
export type ProbeEntry =
  | {
      path: string
      url: string | null
      kind: ProbeKind
      width: number
      height: number
      duration_s: number
      fps: number
      has_audio: boolean
      orientation: string
      error?: undefined
    }
  | { path: string; error: string }

/** GET /api/waveform. */
export interface Waveform {
  duration: number
  peaks_per_second: number
  peaks: number[]
}

export interface SyncRequest {
  master: string
  others: string[]
  master_stream?: number
  stream?: number
}

export interface SyncResult {
  path: string
  offset_s: number
  confidence: number
  reliable: boolean
}

/* ---------- conferência do vídeo renderizado ---------- */

export interface QaSheetRequest {
  video: string
  cols?: number
  rows?: number
  width?: number
}

export interface QaSheetResponse {
  image: string
  url: string | null
}

export interface QaFrameRequest {
  video: string
  /** Instante do quadro, em segundos. */
  t: number
  width?: number
}

export interface QaFrameResponse extends QaSheetResponse {
  t: number
}

/* ---------- layouts de tela ---------- */

/** Layout salvo: onde cada painel fica, o tamanho dos divisores e o que está oculto. */
export interface ScreenLayout {
  version?: number
  areas: Record<string, string>
  sizes: Record<string, number>
  hidden: string[]
  /** Aba aberta ao aplicar o layout (`timeline` ou `voice`); sem valor, a aba atual fica. */
  tab?: string | null
}

export type LayoutPanel = 'player' | 'filters' | 'media' | 'timeline' | 'progress' | 'properties' | 'sidebar' | 'voice'

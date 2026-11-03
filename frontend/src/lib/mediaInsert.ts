/* O que cada gesto do painel Mídia vira em operações do servidor: soltar um arquivo na linha do tempo, as teclas A e V,
   e os botões "+ Arquivo", Texto, Cartão, Logo e Música. Funções puras: recebem a vista, a spec e o instante, e devolvem as
   operações ou o aviso para a pessoa. Quem as executa é `useMediaActions`. */
import type { EditOperation, TimelineView } from '@/api'
import { lockedMessage, type Plan } from './editorActions'
import { baseName } from './format'
import type { MediaEntry, MediaEntryKind } from './media'
import { roundSeconds, v1InsertIndexAt } from './timeline'

/** As extensões que cada tipo de arquivo costuma ter; o que não está em nenhuma lista entra como vídeo. */
export const VIDEO_EXTENSIONS = ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v']
export const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp']
export const AUDIO_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg']

/** Quanto dura, por padrão, um texto, um logo ou um vídeo sobreposto criado a partir do cursor (segundos). */
export const NEW_OVERLAY_SECONDS = 3
/** O volume de uma música recém-escolhida: baixo, para ela entrar por baixo da voz. */
export const NEW_MUSIC_VOLUME = 0.18

const fail = (message: string): Plan => ({ ok: false, message })

/** Vídeo, imagem ou áudio, pela extensão do arquivo. */
export function kindFromPath(path: string): MediaEntryKind {
  const dot = path.lastIndexOf('.')
  const extension = dot < 0 ? '' : path.slice(dot).toLowerCase()
  if (IMAGE_EXTENSIONS.includes(extension)) return 'image'
  if (AUDIO_EXTENSIONS.includes(extension)) return 'audio'
  return 'clip'
}

/** A entrada de mídia de um arquivo escolhido no navegador de arquivos do servidor. */
export function entryFromPath(path: string): MediaEntry {
  return { id: `file:${path}`, kind: kindFromPath(path), label: baseName(path), path, src: path }
}

/** Lê o que o arrastar levou na transferência; texto que não é uma entrada de mídia vale nada. */
export function parseMediaPayload(text: string): MediaEntry | null {
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    return null
  }
  if (data === null || typeof data !== 'object') return null
  const entry = data as Record<string, unknown>
  const kindOk = entry.kind === 'clip' || entry.kind === 'image' || entry.kind === 'audio'
  if (!kindOk || typeof entry.id !== 'string' || typeof entry.path !== 'string') return null
  if (typeof entry.src !== 'string' && typeof entry.source !== 'string') return null
  return {
    id: entry.id,
    kind: entry.kind as MediaEntryKind,
    label: typeof entry.label === 'string' ? entry.label : baseName(entry.path),
    path: entry.path,
    ...(typeof entry.src === 'string' ? { src: entry.src } : {}),
    ...(typeof entry.source === 'string' ? { source: entry.source } : {}),
  }
}

/** A duração de um arquivo para a lista: "3,4 s" e, a partir de um minuto, "1:05". */
export function mediaDurationLabel(seconds: number): string {
  if (seconds >= 60) {
    const total = Math.round(seconds)
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
  }
  return `${seconds.toFixed(1).replace('.', ',')} s`
}

export function kindLabel(kind: MediaEntryKind): string {
  return { clip: 'vídeo', image: 'imagem', audio: 'áudio' }[kind]
}

/* ---------- o trecho e a sobreposição que uma entrada vira ---------- */

/** O trecho da V1 de uma entrada: imagem com movimento suave ou clipe inteiro (da fonte sincronizada, quando é ela). */
export function segmentFromEntry(entry: MediaEntry): Record<string, unknown> {
  if (entry.kind === 'image') return { type: 'image', src: entry.src, duration: 3, motion: 'zoom-in', motion_amount: 0.12 }
  const base = { type: 'clip', start: 0, speed: 1, volume: 1, mute: false }
  return entry.source ? { ...base, source: entry.source } : { ...base, src: entry.src }
}

/** O fim de uma sobreposição criada em `time`: três segundos depois, sem passar do fim do vídeo. Sem espaço, sem fim. */
function overlayEnd(time: number, total: number): { end?: number } {
  const end = roundSeconds(Math.min(total, time + NEW_OVERLAY_SECONDS))
  return end > time ? { end } : {}
}

/** A sobreposição de uma entrada solta fora da V1: imagem no canto, ou o vídeo (a fonte ou o arquivo) como PiP. */
export function overlayFromEntry(entry: MediaEntry, time: number, total: number): Record<string, unknown> {
  const span = { start: roundSeconds(time), ...overlayEnd(time, total) }
  if (entry.kind === 'image') {
    return { type: 'image', src: entry.src, position: 'top-right', width: 0.22, opacity: 1, ...span }
  }
  const base = {
    type: 'video',
    ...span,
    offset: 0,
    position: 'bottom-right',
    width: 0.28,
    shape: 'rounded',
    volume: 1,
    animation: 'fade',
    fade: 0.3,
  }
  return entry.source ? { ...base, source: entry.source } : { ...base, src: entry.src }
}

/* ---------- os planos ---------- */

function trackLocked(view: TimelineView, trackId: string): boolean {
  return view.tracks.find((track) => track.id === trackId)?.locked === true
}

function v1Length(view: TimelineView): number {
  return view.tracks.find((track) => track.id === 'V1')?.items.length ?? 0
}

function insertSegment(view: TimelineView, entry: MediaEntry, index: number): Plan {
  if (entry.kind === 'audio') return fail('Arquivos de áudio entram pelo botão "Música", não na V1.')
  if (trackLocked(view, 'V1')) return fail(lockedMessage('V1'))
  return { ok: true, ops: [{ type: 'insert', index, segment: segmentFromEntry(entry) }] }
}

/** A tecla A, o duplo clique e "+ Arquivo": a entrada vai para o fim da V1. */
export function planAppend(view: TimelineView, entry: MediaEntry): Plan {
  return insertSegment(view, entry, v1Length(view))
}

/** A tecla V: a entrada vai para a V1 na posição do cursor. */
export function planInsertAtTime(view: TimelineView, entry: MediaEntry, time: number): Plan {
  return insertSegment(view, entry, v1InsertIndexAt(view, time))
}

/** Acrescenta uma sobreposição à lista da spec. Não há operação de "inserir sobreposição": vai a lista inteira. */
function addOverlay(overlays: readonly unknown[], overlay: Record<string, unknown>): EditOperation {
  return { type: 'set_field', path: 'overlays', value: [...overlays, overlay] }
}

/**
 * Soltar a entrada na linha do tempo: na V1 ela entra na posição do ponto; em qualquer outra trilha vira uma
 * sobreposição (vídeo como PiP, imagem no canto). Fora das trilhas não há onde soltar.
 */
export function planDrop(
  view: TimelineView,
  overlays: readonly unknown[],
  entry: MediaEntry,
  hit: { trackId: string | null; time: number },
): Plan {
  if (!hit.trackId) return fail('Solte o arquivo sobre uma trilha da linha do tempo.')
  if (hit.trackId === 'V1') return insertSegment(view, entry, v1InsertIndexAt(view, hit.time))
  if (entry.kind === 'audio') return fail('Arquivos de áudio entram pelo botão "Música", não como sobreposição.')
  if (trackLocked(view, hit.trackId)) return fail(lockedMessage(hit.trackId))
  return { ok: true, ops: [addOverlay(overlays, overlayFromEntry(entry, hit.time, view.total))] }
}

/** O botão Texto: uma linha de texto no cursor, para a pessoa editar. */
export function planAddText(view: TimelineView, overlays: readonly unknown[], time: number): Plan {
  if (trackLocked(view, 'TX')) return fail(lockedMessage('TX'))
  const overlay = { type: 'text', text: 'Novo texto', role: 'title', start: roundSeconds(time), ...overlayEnd(time, view.total) }
  return { ok: true, ops: [addOverlay(overlays, overlay)] }
}

/** O botão Logo: o logo da marca no canto, no cursor. */
export function planAddLogo(view: TimelineView, overlays: readonly unknown[], time: number): Plan {
  if (trackLocked(view, 'GR')) return fail(lockedMessage('GR'))
  const overlay = {
    type: 'image',
    src: 'logo',
    position: 'top-right',
    width: 0.22,
    start: roundSeconds(time),
    ...overlayEnd(time, view.total),
  }
  return { ok: true, ops: [addOverlay(overlays, overlay)] }
}

/** O botão Cartão: um cartão de título no fim da V1. */
export function planAddCard(view: TimelineView): Plan {
  if (trackLocked(view, 'V1')) return fail(lockedMessage('V1'))
  const segment = { type: 'card', title: 'Novo cartão', duration: 3, motion: 'zoom-in' }
  return { ok: true, ops: [{ type: 'insert', index: v1Length(view), segment }] }
}

/**
 * O botão Música: o arquivo vira a música do projeto. Se o projeto já tem música, troca só o arquivo e mantém o
 * volume, o ducking e os trechos dela; sem música, cria uma com volume baixo.
 */
export function planSetMusic(currentMusic: unknown, path: string): Plan {
  const hasMusic = currentMusic !== null && typeof currentMusic === 'object'
  const op: EditOperation = hasMusic
    ? { type: 'set_field', path: 'audio.music.src', value: path }
    : { type: 'set_field', path: 'audio.music', value: { src: path, volume: NEW_MUSIC_VOLUME } }
  return { ok: true, ops: [op] }
}

/** O botão "+ Arquivo": áudio vira a música do projeto; vídeo e imagem entram no fim da V1. */
export function planAddFile(view: TimelineView, currentMusic: unknown, path: string): Plan {
  const entry = entryFromPath(path)
  return entry.kind === 'audio' ? planSetMusic(currentMusic, path) : planAppend(view, entry)
}

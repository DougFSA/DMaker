/* O que cada comando de edição da linha do tempo (cortar, remover, lift, duplicar, aparar, mudo/ocultar/bloquear)
   vira em operações do servidor, dado o que está selecionado e onde o cursor está. Funções puras: devolvem as
   operações ou o aviso para a pessoa, e quem as executa é `useEditorActions`. */
import type { EditOperation, TimelineItem, TimelineView } from '@/api'
import { headerButtons, isOverlayTrack, itemCovering, MIN_ITEM_SECONDS, roundSeconds, type TrackToggle } from './timeline'

/** Um item selecionado, junto da trilha onde ele está. */
export interface SelectedEntry {
  trackId: string
  item: TimelineItem
}

export type Plan = { ok: true; ops: EditOperation[] } | { ok: false; message: string }

const fail = (message: string): Plan => ({ ok: false, message })

/** A distância mínima do cursor às pontas do trecho para o corte ter dois pedaços de verdade (segundos). */
const MIN_CUT_MARGIN = 0.02

function lockedMessage(trackId: string): string {
  return `A trilha ${trackId} está bloqueada (cadeado no cabeçalho).`
}

/**
 * Da seleção, o que dá para editar (trecho da V1 ou sobreposição) e não está numa trilha bloqueada. Se a seleção
 * só tinha itens bloqueados, o aviso diz isso em vez de dizer que não há seleção.
 */
function editableEntries(view: TimelineView, selected: readonly SelectedEntry[]): { entries: SelectedEntry[]; locked: string | null } {
  const lockedIds = new Set(view.tracks.filter((track) => track.locked).map((track) => track.id))
  const candidates = selected.filter(({ trackId, item }) => trackId === 'V1' || isOverlayTrack(trackId, item))
  const entries = candidates.filter(({ trackId }) => !lockedIds.has(trackId))
  const firstLocked = candidates.find(({ trackId }) => lockedIds.has(trackId))
  return { entries, locked: entries.length === 0 && firstLocked ? firstLocked.trackId : null }
}

/** Do maior índice para o menor: tirar ou copiar um item desloca os índices dos que vêm depois, não dos que vêm antes. */
function descending(entries: readonly SelectedEntry[]): SelectedEntry[] {
  return [...entries].sort((a, b) => b.item.index - a.item.index)
}

/** Corta no cursor o trecho da V1 selecionado ou, sem seleção, o que está sob o cursor. */
export function planSplit(view: TimelineView, selected: readonly SelectedEntry[], playhead: number): Plan {
  const v1 = view.tracks.find((track) => track.id === 'V1')
  if (v1?.locked) return fail(lockedMessage('V1'))
  const chosen = selected.find((entry) => entry.trackId === 'V1')?.item ?? itemCovering(v1, playhead)
  if (!chosen) return fail('Não há trecho da V1 sob o cursor.')
  const at = playhead - chosen.start
  if (at <= MIN_CUT_MARGIN || at >= chosen.end - chosen.start - MIN_CUT_MARGIN) {
    return fail('Posicione o cursor dentro do trecho para cortar.')
  }
  return { ok: true, ops: [{ type: 'split', index: chosen.index, at: roundSeconds(at) }] }
}

/** Remove os itens selecionados. Na V1 o servidor fecha a lacuna (ripple); `verb` é o que o aviso diz ("remover", "o lift"). */
export function planRemove(view: TimelineView, selected: readonly SelectedEntry[], verb = 'remover'): Plan {
  const { entries, locked } = editableEntries(view, selected)
  if (locked) return fail(lockedMessage(locked))
  if (entries.length === 0) return fail(`Selecione um trecho ou sobreposição para ${verb}.`)
  return {
    ok: true,
    ops: descending(entries).map(({ trackId, item }) =>
      trackId === 'V1' ? { type: 'remove', index: item.index } : { type: 'overlay_remove', index: item.index },
    ),
  }
}

/** Copia cada item selecionado para logo depois dele. */
export function planDuplicate(view: TimelineView, selected: readonly SelectedEntry[]): Plan {
  const { entries, locked } = editableEntries(view, selected)
  if (locked) return fail(lockedMessage(locked))
  if (entries.length === 0) return fail('Selecione um trecho ou sobreposição para duplicar.')
  return {
    ok: true,
    ops: descending(entries).map(({ trackId, item }) =>
      trackId === 'V1' ? { type: 'duplicate', index: item.index } : { type: 'overlay_duplicate', index: item.index },
    ),
  }
}

/** Apara a entrada ou a saída do item selecionado (ou do trecho da V1 sob o cursor) até o cursor. */
export function planTrim(view: TimelineView, selected: readonly SelectedEntry[], side: 'in' | 'out', playhead: number): Plan {
  const { entries, locked } = editableEntries(view, selected)
  if (locked) return fail(lockedMessage(locked))
  const v1 = view.tracks.find((track) => track.id === 'V1')
  const under = itemCovering(v1, playhead)
  const target = entries[0] ?? (under && !v1?.locked ? { trackId: 'V1', item: under } : null)
  if (!target) return fail('Selecione um trecho ou sobreposição para aparar.')
  const { trackId, item } = target
  if (trackId === 'V1') {
    const delta = side === 'in' ? playhead - item.start : playhead - item.end
    return { ok: true, ops: [{ type: 'trim', index: item.index, side, delta: roundSeconds(delta) }] }
  }
  const start = side === 'in' ? playhead : item.start
  const end = side === 'out' ? playhead : item.end
  if (end - start < MIN_ITEM_SECONDS) return fail('O cursor precisa ficar dentro do intervalo da sobreposição.')
  return { ok: true, ops: [{ type: 'overlay_span', index: item.index, start: roundSeconds(start), end: roundSeconds(end) }] }
}

/** A trilha que um atalho de trilha (Ctrl+M, Ctrl+H, Ctrl+L) atinge: a do primeiro item selecionado ou, sem seleção, a sob o mouse. */
export function shortcutTrack(selected: readonly SelectedEntry[], hoverTrackId: string | null): string | null {
  return selected[0]?.trackId ?? hoverTrackId
}

/**
 * Liga ou desliga mudo, ocultar ou bloquear numa trilha. Só vale se o cabeçalho da trilha tem aquele botão (a V1
 * não se oculta e uma trilha de vídeo não se silencia).
 */
export function planTrackToggle(view: TimelineView, trackId: string | null, field: TrackToggle): Plan {
  const track = trackId ? view.tracks.find((candidate) => candidate.id === trackId) : undefined
  if (!track) return fail('Selecione um item ou passe o mouse sobre uma trilha.')
  if (!headerButtons(track).includes(field)) return fail(`A trilha ${track.id} não tem esse controle.`)
  return { ok: true, ops: [{ type: 'set_field', path: `tracks.${track.id}.${field}`, value: !track[field] }] }
}

/** Todos os trechos da V1, para o "selecionar tudo". */
export function v1ItemIds(view: TimelineView): string[] {
  return (view.tracks.find((track) => track.id === 'V1')?.items ?? []).map((item) => item.id)
}

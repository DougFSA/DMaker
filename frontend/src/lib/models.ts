/* Funções puras da tela de Modelos: rótulo e cor do estado, o que escrever na coluna "No disco", o texto dos
   botões, o resumo do disco e o aviso de apagar sobras. O servidor já mede e formata os tamanhos (base 1024,
   vírgula decimal); aqui só se escolhe o que dizer. Sem rede e sem DOM. */
import type { ModelInventory, ModelLeftover, ModelState, ModelStatus } from '@/api'
import type { BadgeTone } from '@/components/ui/AppBadge.vue'

const STATE_LABELS: Record<ModelState, string> = {
  installed: 'baixado',
  partial: 'incompleto',
  absent: 'não baixado',
}

const STATE_TONES: Record<ModelState, BadgeTone> = {
  installed: 'success',
  partial: 'warning',
  absent: 'neutral',
}

export function stateLabel(state: ModelState): string {
  return STATE_LABELS[state] ?? state
}

export function stateTone(state: ModelState): BadgeTone {
  return STATE_TONES[state] ?? 'neutral'
}

/** O que a coluna "No disco" mostra: o tamanho medido, ou quanto vai ocupar quando ainda não há nada. */
export function sizeCell(model: ModelStatus): { size: string; note: string } {
  if (model.state === 'absent') return { size: '', note: `ocupa ~${model.expected_label} ao baixar` }
  if (model.state === 'partial') return { size: model.size_label, note: `de ~${model.expected_label}` }
  return { size: model.size_label, note: '' }
}

/** Só o que não está inteiro se baixa (ou se continua, quando há um download pela metade). */
export function canDownload(model: ModelStatus): boolean {
  return model.state !== 'installed'
}

/** Só o que tem alguma coisa em disco se apaga, inclusive o download pela metade. */
export function canRemove(model: ModelStatus): boolean {
  return model.state !== 'absent'
}

export function downloadLabel(model: ModelStatus): string {
  return model.state === 'partial' ? 'Continuar download' : `Baixar (${model.expected_label})`
}

/** "Usado por: Narração; Dublagem", ou vazio quando nenhuma função depende do modelo. */
export function usedByText(model: ModelStatus): string {
  return model.required_by.length ? `Usado por: ${model.required_by.join('; ')}` : ''
}

/** A linha-resumo do disco: quanto os modelos ocupam, quanto sobra livre e quanto é sobra. */
export function summaryParts(inventory: ModelInventory): string[] {
  const parts = [`Ocupado em cache/models: ${inventory.total_label}`]
  if (inventory.disk_free_label) parts.push(`Livre no disco: ${inventory.disk_free_label}`)
  if (inventory.leftovers.length) parts.push(`Sobras: ${inventory.leftover_label}`)
  return parts
}

/** Uma sobra como a lista a mostra: o caminho (com barra no fim se for pasta) e o tamanho. */
export function leftoverLine(item: ModelLeftover): string {
  return `${item.path}${item.is_dir ? '/' : ''}: ${item.size_label}`
}

export function leftoversTotal(inventory: ModelInventory): string {
  return `${inventory.leftovers.length} item(ns), ${inventory.leftover_label}`
}

/** O aviso do diálogo de apagar sobras: quanto some e o pedido para conferir a lista antes. */
export function pruneWarning(inventory: ModelInventory): string {
  return (
    `Vai apagar ${inventory.leftovers.length} item(ns) que nenhum modelo do DMaker usa e liberar ${inventory.leftover_label}. ` +
    'Confira a lista: se algum é de um modelo seu, cancele.'
  )
}

/** Uma lista curta numa linha só (o diálogo de confirmação mostra um parágrafo): os primeiros itens e quantos ficaram de fora. */
export function listPreview(lines: string[], limit = 6): string {
  const shown = lines.slice(0, limit).join(' · ')
  const hidden = lines.length - limit
  return hidden > 0 ? `${shown} · e mais ${hidden}` : shown
}

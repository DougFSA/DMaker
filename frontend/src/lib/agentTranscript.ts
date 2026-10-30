/* A transcrição que o servidor guarda (api/types/agent.ts) vira os mesmos itens do turno ao vivo, para a conversa
   salva e a que acabou de chegar serem desenhadas pelos mesmos componentes. */
import type { TranscriptEntry } from '@/api'
import type { ChatItem } from './agent'
import { cardOfSummary } from './agentAttachments'

/**
 * Cada entrada vira um item com o mesmo id. A confirmação sem resposta (`unconfirmed`), a ferramenta que o
 * DMaker interrompeu e os avisos têm estado próprio; o aviso de erro é o mesmo item de erro do turno ao vivo.
 */
export function itemsFromTranscript(entries: TranscriptEntry[]): ChatItem[] {
  const items: ChatItem[] = []
  for (const entry of entries) {
    switch (entry.kind) {
      case 'user':
        items.push({
          kind: 'user',
          id: entry.id,
          text: entry.text,
          ...(entry.attachments?.length ? { attachments: entry.attachments.map(cardOfSummary) } : {}),
        })
        break
      case 'kits':
        items.push({ kind: 'kits', id: entry.id, kits: entry.kits, method: entry.method })
        break
      case 'thinking':
        items.push({ kind: 'thinking', id: entry.id, text: entry.text, streaming: false })
        break
      case 'tool':
        items.push({
          kind: 'tool',
          id: entry.id,
          name: entry.name,
          arguments: entry.arguments,
          state: entry.state,
          detail: entry.detail,
          result: entry.result,
          percent: null,
          label: '',
        })
        break
      case 'confirmation':
        items.push({
          kind: 'confirmation',
          id: entry.id,
          confirmationId: entry.confirmation_id,
          tool: entry.tool,
          question: entry.question,
          type: entry.type,
          state: entry.state,
        })
        break
      case 'answer':
        items.push({ kind: 'answer', id: entry.id, text: entry.text, interrupted: entry.interrupted, streaming: false })
        break
      case 'notice':
        items.push(
          entry.level === 'error' && entry.code === 'error'
            ? { kind: 'error', id: entry.id, text: entry.text }
            : { kind: 'notice', id: entry.id, level: entry.level, code: entry.code, text: entry.text },
        )
        break
      default:
        break // uma entrada de um tipo que esta tela ainda não conhece não derruba a conversa
    }
  }
  return items
}

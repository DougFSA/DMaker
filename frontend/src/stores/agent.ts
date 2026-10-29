import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, errorMessage, type AgentStatus } from '@/api'
import { pendingConfirmation, reduceEvent, type ChatItem, type StreamEvent } from '@/lib/agent'

/** Conversa com o agente local: as mensagens, o job da resposta em andamento e o SSE que o conta ao vivo. */
export const useAgentStore = defineStore('agent', () => {
  const status = ref<AgentStatus | null>(null)
  const items = ref<ChatItem[]>([])
  const conversationId = ref<string | null>(null)
  const jobId = ref<string | null>(null)
  const busy = ref(false)
  const error = ref('')

  let source: EventSource | null = null
  let turnBase = 0
  let counter = 0

  const nextId = () => `item-${(counter += 1)}`
  const waitingForYou = computed(() => pendingConfirmation(items.value))
  const ready = computed(() => !!status.value?.reachable && !!status.value?.model_installed)

  async function loadStatus(): Promise<void> {
    try {
      status.value = await api.agent.status()
      error.value = ''
    } catch (failure) {
      status.value = null
      error.value = errorMessage(failure)
    }
  }

  function closeSource(): void {
    source?.close()
    source = null
  }

  function applyEvent(event: StreamEvent): void {
    items.value = reduceEvent(items.value, event, turnBase, nextId)
    if (event.kind === 'end') {
      busy.value = false
      jobId.value = null
      closeSource()
    }
  }

  function follow(id: string): void {
    closeSource()
    source = new EventSource(api.jobs.eventsUrl(id))
    source.onmessage = (message) => applyEvent(JSON.parse(message.data) as StreamEvent)
    source.onerror = () => {
      // o servidor encerra o fluxo no fim do job; só um erro com a conexão fechada de vez interessa
      if (source && source.readyState === EventSource.CLOSED && busy.value) {
        busy.value = false
        error.value = 'Perdi a conexão com o servidor do DMaker durante a resposta.'
      }
    }
  }

  /** Manda a mensagem e passa a acompanhar a resposta. Devolve `false` se não foi enviada (erro mostrado em `error`). */
  async function send(message: string): Promise<boolean> {
    const text = message.trim()
    if (!text || busy.value) return false
    error.value = ''
    try {
      const response = await api.agent.send(text, conversationId.value)
      conversationId.value = response.conversation_id
      items.value = [...items.value, { kind: 'user', id: nextId(), text }]
      turnBase = items.value.length
      jobId.value = response.job_id
      busy.value = true
      follow(response.job_id)
      return true
    } catch (failure) {
      error.value = errorMessage(failure)
      return false
    }
  }

  async function answerConfirmation(confirmationId: string, approve: boolean): Promise<void> {
    if (!conversationId.value) return
    try {
      await api.agent.confirm(conversationId.value, confirmationId, approve)
    } catch (failure) {
      error.value = errorMessage(failure)
    }
  }

  /** Nova conversa: o servidor esquece o histórico e a tela começa vazia. */
  async function reset(): Promise<void> {
    closeSource()
    if (conversationId.value && !busy.value) {
      try {
        await api.agent.reset(conversationId.value)
      } catch {
        // a conversa pode já não existir no servidor (ele reiniciou); começar de novo é o que se quer mesmo assim
      }
    }
    items.value = []
    conversationId.value = null
    jobId.value = null
    busy.value = false
    error.value = ''
    turnBase = 0
  }

  return { status, items, conversationId, jobId, busy, error, waitingForYou, ready, loadStatus, send, answerConfirmation, reset }
})

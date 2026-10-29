import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  api,
  errorMessage,
  subscribeJson,
  type QueueAdded,
  type QueueAudioFormat,
  type QueueView,
  type SseStatus,
  type SseSubscription,
} from '@/api'
import { ACTION_FAILURES, canClearFinished, moveLimits, queueSummary, type QueueAction } from '@/lib/queue'
import { useNarrationStore } from './narration'
import { useToastsStore } from './toasts'

/** O que o "Importar" pede além do arquivo; a voz, o idioma e a velocidade vêm da Narração. */
export interface ImportChoices {
  title: string
  format: QueueAudioFormat
  draft: boolean
}

/**
 * A fila de narrações: a foto da fila que o servidor manda a cada mudança (SSE), os comandos sobre cada item e a
 * importação de roteiros. A fila roda no servidor, sozinha; aqui só se acompanha e se comanda. A tela abre o
 * acompanhamento ao montar (`start`) e fecha ao sair (`stop`).
 */
export const useQueueStore = defineStore('queue', () => {
  const toasts = useToastsStore()
  const narration = useNarrationStore()

  const view = ref<QueueView | null>(null)
  const status = ref<SseStatus>('closed')
  /** Por que a fila não carregou; some assim que uma foto chega. */
  const failure = ref('')
  /** Os itens com um comando em andamento: o botão deles espera a resposta antes de aceitar outro. */
  const working = ref<Record<string, true>>({})
  const importing = ref(false)
  const clearing = ref(false)

  const items = computed(() => view.value?.items ?? [])
  const summary = computed(() => (view.value ? queueSummary(view.value) : null))
  const limits = computed(() => moveLimits(items.value))
  const canClear = computed(() => (view.value ? canClearFinished(view.value) : false))
  /** A conexão com o servidor caiu e a tela tenta de novo: o que está na lista pode estar velho. */
  const offline = computed(() => status.value === 'reconnecting')

  let subscription: SseSubscription | null = null
  let streamed = false

  /** Abre o acompanhamento ao vivo e lê a fila uma vez, para a tela não esperar a primeira foto do fluxo. */
  async function start(): Promise<void> {
    if (subscription) return
    streamed = false
    subscription = subscribeJson<QueueView>(
      api.queue.eventsUrl,
      (frame) => {
        streamed = true
        failure.value = ''
        view.value = frame
      },
      { onStatus: (next) => (status.value = next) },
    )
    await reload()
  }

  function stop(): void {
    subscription?.close()
    subscription = null
  }

  /** Lê a fila agora. Uma foto do fluxo que já chegou é mais nova que esta leitura, então ela não a sobrescreve. */
  async function reload(): Promise<void> {
    try {
      const fresh = await api.queue.list()
      if (!streamed) view.value = fresh
      failure.value = ''
    } catch (error) {
      if (!view.value) failure.value = errorMessage(error)
    }
  }

  function send(id: string, action: QueueAction): Promise<QueueView> {
    switch (action) {
      case 'up':
        return api.queue.move(id, -1)
      case 'down':
        return api.queue.move(id, 1)
      case 'remove':
        return api.queue.remove(id)
      default:
        return api.queue[action](id)
    }
  }

  /** Manda um comando ao item. A resposta já traz a fila nova; um erro vira aviso com a frase do servidor. */
  async function act(id: string, action: QueueAction): Promise<void> {
    if (working.value[id]) return
    working.value = { ...working.value, [id]: true }
    try {
      view.value = await send(id, action)
    } catch (error) {
      toasts.push({ tone: 'error', title: ACTION_FAILURES[action], description: errorMessage(error) })
    } finally {
      const rest = { ...working.value }
      delete rest[id]
      working.value = rest
    }
  }

  /** Tira da lista os itens prontos e cancelados; os áudios continuam na pasta de saída. */
  async function clearFinished(): Promise<void> {
    if (clearing.value) return
    clearing.value = true
    try {
      const cleared = await api.queue.clearFinished()
      view.value = cleared
      toasts.push({
        tone: 'info',
        title: cleared.removed === 1 ? '1 item saiu da lista' : `${cleared.removed} itens saíram da lista`,
        description: 'Os áudios continuam na pasta de saída.',
      })
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui limpar a lista', description: errorMessage(error) })
    } finally {
      clearing.value = false
    }
  }

  /**
   * Põe um roteiro de arquivo no fim da fila, com a voz, o idioma, a velocidade e a marca que a Narração tem agora (a
   * mesma regra da clássica). Devolve o item novo, ou nulo se o servidor recusou (o aviso já foi dado).
   */
  async function importScript(file: File, choices: ImportChoices): Promise<QueueAdded | null> {
    importing.value = true
    try {
      const added = await api.queue.addFile({
        file,
        filename: file.name,
        ...(choices.title.trim() ? { title: choices.title.trim() } : {}),
        voice: narration.voiceId || null,
        language: narration.language || null,
        speed: narration.speed,
        brand: narration.brand || null,
        draft: choices.draft,
        format: choices.format,
      })
      view.value = added
      toasts.push({
        tone: 'success',
        title: 'Roteiro na fila',
        description: 'Ele será narrado em segundo plano, um por vez.',
      })
      return added
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui importar o roteiro', description: errorMessage(error) })
      return null
    } finally {
      importing.value = false
    }
  }

  return {
    view,
    status,
    failure,
    working,
    importing,
    clearing,
    items,
    summary,
    limits,
    canClear,
    offline,
    start,
    stop,
    reload,
    act,
    clearFinished,
    importScript,
  }
})

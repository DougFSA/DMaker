import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  api,
  ApiError,
  errorMessage,
  followJob,
  isJobCancelled,
  type AgentConversationCreate,
  type AgentConversationDetail,
  type AgentConversationPatch,
  type AgentConversationSummary,
  type AgentLoaded,
  type AgentMessageRequest,
  type AgentMode,
  type AgentModels,
  type AgentOptions,
  type AgentStatus,
} from '@/api'
import {
  dropAfterLastUser,
  pendingConfirmation,
  reduceEvent,
  stageOf,
  type ChatItem,
  type StageInfo,
  type StreamEvent,
} from '@/lib/agent'
import { hasOptions, optionsFrom, sameOptions, valuesOf } from '@/lib/agentAdvanced'
import {
  attachmentOnlyMessage,
  attachmentWarnings,
  cardOfAttachment,
  failedCard,
  MAX_ATTACHMENTS,
  splitPicked,
  suggestedModelsOf,
  uploadingCard,
  type AttachmentCard,
} from '@/lib/agentAttachments'
import { effortAfterModelChange, findModel, memoryNotice, needsMemoryConfirmation, toolsNotice } from '@/lib/agentModels'
import { itemsFromTranscript } from '@/lib/agentTranscript'
import { readStored, removeStored, writeStored } from '@/lib/storage'
import { useToastsStore } from './toasts'

/** A conversa aberta é lembrada no navegador: recarregar a página (F5) volta nela. */
export const OPEN_CONVERSATION_KEY = 'dmaker.agent.conversation'

const TITLE_LIMIT = 60
const CONNECTION_LOST =
  'Perdi a conexão com o servidor do DMaker durante a resposta. Abra a conversa de novo para ver o que foi salvo.'

/** O que a conversa nova vai ter: ainda não existe no servidor, que a cria junto com a primeira mensagem. */
interface Draft {
  mode: AgentMode
  /** Vazio: o modelo padrão do ambiente. */
  model: string
  effort: string | null
  options: AgentOptions
}

const NEW_DRAFT: Draft = { mode: 'operate', model: '', effort: null, options: {} }

/** A conversa que acabou de nascer no servidor, até o detalhe de verdade chegar. */
function provisionalDetail(id: string, jobId: string, text: string, draft: Draft, model: string): AgentConversationDetail {
  const now = new Date().toISOString()
  return {
    id,
    title: text.length > TITLE_LIMIT ? `${text.slice(0, TITLE_LIMIT - 1)}…` : text,
    created_at: now,
    updated_at: now,
    mode: draft.mode,
    model,
    effort: draft.effort,
    messages: 1,
    running: true,
    options: draft.options,
    kits: [],
    mode_locked: true,
    running_job_id: jobId,
    pending_attachments: [],
    transcript: [],
  }
}

function summaryOf(detail: AgentConversationDetail): AgentConversationSummary {
  const { id, title, created_at, updated_at, mode, model, effort, messages, running } = detail
  return { id, title, created_at, updated_at, mode, model, effort, messages, running }
}

/**
 * As conversas com o agente local: a lista salva no servidor, a que está aberta, o modelo e o esforço dela, e o turno
 * em andamento (o job da resposta, acompanhado pelo SSE, com a resposta crescendo e o botão Parar).
 */
export const useAgentStore = defineStore('agent', () => {
  const status = ref<AgentStatus | null>(null)
  /** O servidor já respondeu (ou falhou) ao menos uma vez: antes disso a tela não tem o que reclamar. */
  const statusChecked = ref(false)
  const models = ref<AgentModels | null>(null)
  const conversations = ref<AgentConversationSummary[]>([])
  /** A conversa aberta; `null` é a conversa nova que só passa a existir quando a primeira mensagem é enviada. */
  const detail = ref<AgentConversationDetail | null>(null)
  const draft = ref<Draft>({ ...NEW_DRAFT })
  const items = ref<ChatItem[]>([])
  const jobId = ref<string | null>(null)
  const busy = ref(false)
  const stopping = ref(false)
  /** A etapa que o servidor informou (carregando o modelo, lendo o pedido...) e quando a tela soube dela. */
  const stage = ref<(StageInfo & { since: number }) | null>(null)
  const error = ref('')
  /** Os arquivos que estão subindo ou que falharam; os que já subiram vêm do detalhe (`pending_attachments`). */
  const uploads = ref<AttachmentCard[]>([])
  /** O que a tela recusou ao escolher arquivos (passou do máximo, vídeo numa Conversa livre), em palavras de quem usa. */
  const attachNotice = ref('')
  /** Os modelos que o servidor sugeriu ao recusar uma imagem, para a pessoa trocar com um clique. */
  const suggestedModels = ref<string[]>([])
  /** O que está carregado na memória agora (só o Ollama); `null` até a primeira leitura. */
  const loaded = ref<AgentLoaded | null>(null)
  const unloading = ref<string | null>(null)
  const unloadError = ref('')

  let following: AbortController | null = null
  let turnBase = 0
  let counter = 0
  let openToken = 0
  let creating: Promise<AgentConversationDetail | null> | null = null

  const nextId = () => `item-${(counter += 1)}`
  const toasts = () => useToastsStore()

  const conversationId = computed(() => detail.value?.id ?? null)
  const mode = computed<AgentMode>(() => detail.value?.mode ?? draft.value.mode)
  const modeLocked = computed(() => detail.value?.mode_locked ?? false)
  const modelName = computed(() => detail.value?.model || draft.value.model || models.value?.default_model || status.value?.model || '')
  const effort = computed(() => (detail.value ? detail.value.effort : draft.value.effort))
  const selectedModel = computed(() => findModel(models.value?.models, modelName.value))
  const memoryWarning = computed(() => memoryNotice(selectedModel.value, models.value?.memory ?? null))
  const confirmsMemory = computed(() => needsMemoryConfirmation(selectedModel.value))
  const waitingForYou = computed(() => pendingConfirmation(items.value))
  /** O modelo escolhido está instalado: pela lista de modelos quando ela veio, senão pelo que o status disse do padrão. */
  const modelInstalled = computed(() => (models.value ? !!selectedModel.value : !!status.value?.model_installed))
  const ready = computed(() => !!status.value?.reachable && modelInstalled.value)
  /** O modelo escolhido não usa ferramentas e a conversa opera o DMaker: o servidor recusaria, então a tela avisa antes. */
  const toolsProblem = computed(() => toolsNotice(selectedModel.value, mode.value))
  /** Pode enviar: o servidor do modelo responde, o modelo está instalado e serve ao modo da conversa. */
  const canSend = computed(() => ready.value && !toolsProblem.value)

  /** O motor do modelo (`ollama` ou `openai`); o que o motor não tem (contexto, descarregar) a tela esconde. */
  const engine = computed(() => models.value?.engine ?? status.value?.engine ?? null)
  const options = computed<AgentOptions>(() => (detail.value ? detail.value.options : draft.value.options))

  // ---------- anexos ----------

  /** As fichas da caixa de mensagem: os anexos já no servidor, depois os que sobem e os que falharam. */
  const attachmentCards = computed<AttachmentCard[]>(() => [
    ...(detail.value?.pending_attachments ?? []).map(cardOfAttachment),
    ...uploads.value,
  ])
  const pendingCount = computed(() => detail.value?.pending_attachments.length ?? 0)
  const uploading = computed(() => uploads.value.some((card) => card.state === 'uploading'))
  /** O que o servidor recusaria nestes anexos (imagem para modelo sem visão, vídeo numa Conversa livre). */
  const warnings = computed(() =>
    attachmentWarnings(attachmentCards.value, mode.value, selectedModel.value, models.value?.models ?? []),
  )
  /** Por que os anexos seguram o envio agora; vazio quando não seguram. */
  const attachmentsBlock = computed(() => (uploading.value ? 'Espere os arquivos terminarem de subir.' : (warnings.value[0]?.text ?? '')))
  /** O botão Enviar pode agir: a conversa está pronta e os anexos não seguram a mensagem. */
  const sendable = computed(() => canSend.value && !attachmentsBlock.value)

  /** O que impede de conversar agora, em palavras de quem usa; vazio quando está tudo certo. */
  const problem = computed(() => {
    if (!statusChecked.value) return ''
    const current = status.value
    if (!current) return error.value || 'Não consegui falar com o servidor do DMaker.'
    if (!current.reachable) return `O modelo local não está respondendo em ${current.url}. Abra o ${current.engine_label}.`
    if (!modelInstalled.value) {
      return `O modelo '${modelName.value}' não está instalado. Escolha outro na barra da conversa ou rode "dmaker doctor --offline" para ver o que falta.`
    }
    return ''
  })

  // ---------- leitura do servidor ----------

  async function loadStatus(): Promise<void> {
    try {
      status.value = await api.agent.status()
      error.value = ''
    } catch (failure) {
      status.value = null
      error.value = errorMessage(failure)
    } finally {
      statusChecked.value = true
    }
  }

  /**
   * Os modelos instalados. Se a leitura falha (o servidor ocupado demora a responder) a lista que já havia continua;
   * sem lista nenhuma a tela mostra só o modelo da conversa.
   */
  async function loadModels(): Promise<void> {
    try {
      models.value = await api.agent.models()
    } catch {
      // mantém a lista anterior
    }
  }

  /** O que está carregado na memória agora. Só o Ollama sabe; se a leitura falha, a que já havia continua. */
  async function loadLoaded(): Promise<void> {
    if (engine.value === 'openai') return
    try {
      loaded.value = await api.agent.loaded()
    } catch {
      // mantém a leitura anterior
    }
  }

  /**
   * Descarrega o modelo da memória. O servidor recusa (409) enquanto uma resposta o usa; o motivo fica em `unloadError`.
   * Devolve se o modelo estava carregado e saiu.
   */
  async function unload(name: string): Promise<boolean> {
    unloading.value = name
    unloadError.value = ''
    try {
      const result = await api.agent.unload(name)
      await Promise.all([loadLoaded(), loadModels()])
      return result.unloaded
    } catch (failure) {
      unloadError.value = errorMessage(failure)
      return false
    } finally {
      unloading.value = null
    }
  }

  async function loadConversations(): Promise<void> {
    try {
      conversations.value = await api.agent.conversations.list()
    } catch (failure) {
      error.value = errorMessage(failure)
    }
  }

  /** A conversa que já estava na lista fica no lugar; a nova abre a lista (é a mais recente). */
  function upsertSummary(summary: AgentConversationSummary): void {
    const known = conversations.value.some((item) => item.id === summary.id)
    conversations.value = known
      ? conversations.value.map((item) => (item.id === summary.id ? summary : item))
      : [summary, ...conversations.value]
  }

  /** Atualiza o resumo da conversa aberta (modo travado, título, modelo) sem tocar nas mensagens da tela. */
  async function refreshDetail(): Promise<void> {
    const id = detail.value?.id
    if (!id) return
    try {
      const fresh = await api.agent.conversations.get(id)
      if (detail.value?.id === id) detail.value = fresh
      upsertSummary(summaryOf(fresh))
    } catch {
      // o resumo antigo continua valendo; a lista se corrige na próxima abertura
    }
  }

  // ---------- o turno em andamento ----------

  function stopFollowing(): void {
    following?.abort()
    following = null
  }

  function applyEvent(event: StreamEvent): void {
    const info = stageOf(event)
    if (info) {
      stage.value = { ...info, since: Date.now() }
      return
    }
    items.value = reduceEvent(items.value, event, turnBase, nextId)
    if (event.kind === 'start') stage.value = null
    if (event.kind === 'end') finishTurn()
  }

  function finishTurn(): void {
    busy.value = false
    stopping.value = false
    jobId.value = null
    stage.value = null
    following = null
    // o fim de um turno muda a ordem da lista, a memória livre e o que está carregado
    void Promise.all([loadConversations(), refreshDetail(), loadModels(), loadLoaded()])
  }

  /** Acompanha o job do turno pelo SSE (reconecta sozinho; o servidor reenvia o turno inteiro desde o `start`). */
  function follow(id: string): void {
    stopFollowing()
    const controller = new AbortController()
    following = controller
    const followed = followJob(id, {
      signal: controller.signal,
      onEvent: (event) => {
        if (following === controller) applyEvent(event as StreamEvent)
      },
    })
    followed.result.then(
      () => undefined,
      (failure: unknown) => {
        // trocar de conversa solta o job sem pará-lo, e o `end` do job (parada ou erro) já virou item na conversa
        if (following !== controller || isJobCancelled(failure) || !busy.value) return
        following = null
        busy.value = false
        stopping.value = false
        stage.value = null
        error.value = CONNECTION_LOST
      },
    )
  }

  /** Manda a mensagem e passa a acompanhar a resposta. Devolve `false` se não foi enviada (erro mostrado em `error`). */
  async function send(message: string): Promise<boolean> {
    const attached = detail.value?.pending_attachments ?? []
    // o servidor exige texto; uma mensagem que só leva anexo diz isso, e a conversa mostra o texto como foi enviado
    const text = message.trim() || attachmentOnlyMessage(attached.length)
    if (!text || busy.value || attachmentsBlock.value) return false
    error.value = ''
    attachNotice.value = ''
    suggestedModels.value = []
    const request: AgentMessageRequest = { message: text }
    const current = detail.value
    if (current) {
      request.conversation_id = current.id
      if (attached.length) request.attachments = attached.map((attachment) => attachment.id)
    } else {
      // a conversa nova nasce no servidor com o modo, o modelo, o esforço e as opções escolhidos na barra
      request.mode = draft.value.mode
      if (modelName.value) request.model = modelName.value
      if (draft.value.effort) request.effort = draft.value.effort
      if (hasOptions(draft.value.options)) request.options = draft.value.options
    }
    try {
      const response = await api.agent.send(request)
      if (!current) {
        detail.value = provisionalDetail(response.conversation_id, response.job_id, text, draft.value, modelName.value)
        upsertSummary(summaryOf(detail.value))
        writeStored(OPEN_CONVERSATION_KEY, response.conversation_id)
      } else if (attached.length && detail.value?.id === current.id) {
        detail.value = { ...detail.value, pending_attachments: [] }
      }
      items.value = [
        ...items.value,
        { kind: 'user', id: nextId(), text, ...(attached.length ? { attachments: attached.map(cardOfAttachment) } : {}) },
      ]
      turnBase = items.value.length
      jobId.value = response.job_id
      busy.value = true
      stopping.value = false
      stage.value = null
      follow(response.job_id)
      void refreshDetail()
      return true
    } catch (failure) {
      // o texto e os anexos continuam como estavam (no servidor, a mensagem recusada deixa os anexos pendentes)
      error.value = errorMessage(failure)
      suggestedModels.value = suggestedModelsOf(failure)
      return false
    }
  }

  /** O Parar: o servidor fecha a conexão com o modelo e o job termina como parado; até o `end` chegar, a tela diz "Parando". */
  async function stop(): Promise<void> {
    const id = detail.value?.id
    if (!id || !busy.value || stopping.value) return
    stopping.value = true
    try {
      await api.agent.conversations.stop(id)
    } catch (failure) {
      // 409: a resposta acabou entre o clique e a chamada; o `end` já vem a caminho (ou já veio)
      if (failure instanceof ApiError && failure.status === 409) return
      stopping.value = false
      error.value = errorMessage(failure)
    }
  }

  async function answerConfirmation(confirmationId: string, approve: boolean): Promise<void> {
    const id = detail.value?.id
    if (!id) return
    try {
      await api.agent.confirm(id, confirmationId, approve)
    } catch (failure) {
      error.value = errorMessage(failure)
    }
  }

  // ---------- abrir, criar e gerir conversas ----------

  function clearConversation(): void {
    stopFollowing()
    items.value = []
    detail.value = null
    jobId.value = null
    busy.value = false
    stopping.value = false
    stage.value = null
    error.value = ''
    uploads.value = []
    attachNotice.value = ''
    suggestedModels.value = []
    turnBase = 0
  }

  /** Mostra a conversa salva; se ela estava respondendo (a página foi recarregada), volta a acompanhar o turno. */
  function show(opened: AgentConversationDetail): void {
    clearConversation()
    detail.value = opened
    writeStored(OPEN_CONVERSATION_KEY, opened.id)
    items.value = itemsFromTranscript(opened.transcript)
    if (!opened.running_job_id) return
    // o SSE reenvia o turno desde o `start`: da transcrição fica só até a mensagem da pessoa, para nada vir duas vezes
    items.value = dropAfterLastUser(items.value)
    turnBase = items.value.length
    jobId.value = opened.running_job_id
    busy.value = true
    follow(opened.running_job_id)
  }

  async function open(id: string): Promise<void> {
    openToken += 1
    const token = openToken
    try {
      const opened = await api.agent.conversations.get(id)
      if (token === openToken) show(opened)
    } catch (failure) {
      if (token !== openToken) return
      if (failure instanceof ApiError && failure.status === 404) removeStored(OPEN_CONVERSATION_KEY)
      error.value = errorMessage(failure)
    }
  }

  /**
   * Conversa nova. Se a aberta ainda está vazia, ela mesma serve: assim não sobram conversas vazias no disco.
   * A conversa nova só passa a existir no servidor com a primeira mensagem.
   */
  function startNew(): void {
    const current = detail.value
    if (current === null || (current.messages === 0 && !items.value.length)) {
      error.value = ''
      attachNotice.value = ''
      // a conversa vazia que serve de rascunho (nasceu para receber um anexo) volta em branco, sem os arquivos de antes
      if (current) void discardPending(current)
      return
    }
    openToken += 1
    clearConversation()
    draft.value = { ...NEW_DRAFT }
    removeStored(OPEN_CONVERSATION_KEY)
  }

  /** Abre a tela: lê o servidor do modelo, os modelos e as conversas, e volta à conversa que estava aberta. */
  async function init(): Promise<void> {
    await Promise.all([loadStatus(), loadModels(), loadConversations()])
    const remembered = readStored(OPEN_CONVERSATION_KEY)
    if (remembered && !detail.value) await open(remembered)
  }

  async function rename(id: string, title: string): Promise<boolean> {
    const clean = title.trim()
    if (!clean) return false
    try {
      const updated = await api.agent.conversations.update(id, { title: clean })
      upsertSummary(summaryOf(updated))
      if (detail.value?.id === id) detail.value = { ...detail.value, title: updated.title }
      return true
    } catch (failure) {
      toasts().push({ tone: 'error', title: 'Não consegui renomear a conversa', description: errorMessage(failure) })
      return false
    }
  }

  /** Apaga a conversa do disco (a tela já pediu a confirmação). Se era a aberta, a tela volta à conversa nova. */
  async function remove(id: string): Promise<boolean> {
    try {
      await api.agent.conversations.remove(id)
    } catch (failure) {
      toasts().push({ tone: 'error', title: 'Não consegui apagar a conversa', description: errorMessage(failure) })
      return false
    }
    conversations.value = conversations.value.filter((item) => item.id !== id)
    if (detail.value?.id === id) {
      openToken += 1
      clearConversation()
      draft.value = { ...NEW_DRAFT }
      removeStored(OPEN_CONVERSATION_KEY)
    }
    return true
  }

  // ---------- anexos ----------

  /**
   * A conversa onde os anexos vão. O servidor exige conversa existente para receber um arquivo, então o rascunho
   * vira conversa aqui, com o modo, o modelo, o esforço e as opções escolhidos; vários arquivos de uma vez criam uma só.
   */
  function ensureConversation(): Promise<AgentConversationDetail | null> {
    if (detail.value) return Promise.resolve(detail.value)
    creating ??= createFromDraft().finally(() => {
      creating = null
    })
    return creating
  }

  async function createFromDraft(): Promise<AgentConversationDetail | null> {
    const body: AgentConversationCreate = { mode: draft.value.mode }
    if (modelName.value) body.model = modelName.value
    if (draft.value.effort) body.effort = draft.value.effort
    if (hasOptions(draft.value.options)) body.options = draft.value.options
    try {
      const created = await api.agent.conversations.create(body)
      // a pessoa pode ter aberto outra conversa enquanto esta nascia: a que já está aberta vale
      if (detail.value) return detail.value
      detail.value = created
      upsertSummary(summaryOf(created))
      writeStored(OPEN_CONVERSATION_KEY, created.id)
      return created
    } catch (failure) {
      error.value = errorMessage(failure)
      return null
    }
  }

  /** Por que não dá para anexar agora (a pessoa vê o motivo no lugar das fichas); vazio quando dá. */
  function attachRefusal(): string {
    if (busy.value) return 'Espere a resposta terminar para anexar arquivos.'
    if (!ready.value) return problem.value || 'O modelo local não está respondendo.'
    if (toolsProblem.value) return toolsProblem.value
    return ''
  }

  /**
   * Sobe os arquivos escolhidos, um depois do outro, e deixa cada um pendente na conversa até a mensagem. A tela recusa
   * antes o que o servidor recusaria (vídeo numa Conversa livre, mais de 8 anexos); o resto, o servidor decide e a
   * recusa dele aparece na ficha do arquivo.
   */
  async function attach(files: File[]): Promise<void> {
    if (!files.length) return
    error.value = ''
    suggestedModels.value = []
    const refusal = attachRefusal()
    if (refusal) {
      attachNotice.value = refusal
      return
    }
    const room = MAX_ATTACHMENTS - pendingCount.value - uploads.value.filter((card) => card.state === 'uploading').length
    const { accepted, notices } = splitPicked(files, mode.value, room)
    attachNotice.value = notices.join(' ')
    if (!accepted.length) return

    const cards = accepted.map((file) => uploadingCard(nextId(), file))
    uploads.value = [...uploads.value, ...cards]
    const conversation = await ensureConversation()
    if (!conversation) {
      uploads.value = uploads.value.filter((item) => !cards.some((card) => card.key === item.key))
      return
    }
    for (const [index, file] of accepted.entries()) {
      const card = cards[index]!
      // a pessoa abriu outra conversa no meio: o que falta não sobe para onde ela não está mais
      if (detail.value?.id !== conversation.id) return
      try {
        const attachment = await api.agent.conversations.attachments.upload(conversation.id, file)
        if (detail.value?.id !== conversation.id) return
        detail.value = { ...detail.value, pending_attachments: [...detail.value.pending_attachments, attachment] }
        uploads.value = uploads.value.filter((item) => item.key !== card.key)
      } catch (failure) {
        if (detail.value?.id !== conversation.id) return
        uploads.value = uploads.value.map((item) => (item.key === card.key ? failedCard(item, errorMessage(failure)) : item))
      }
    }
    // o servidor refaz o corte do texto de cada anexo com o contexto de agora: a ficha mostra o que ele conta
    void refreshDetail()
  }

  /** Tira a ficha: a que falhou só sai da tela; a que já subiu também é apagada no servidor. */
  async function removeAttachment(card: AttachmentCard): Promise<void> {
    attachNotice.value = ''
    const current = detail.value
    if (card.state !== 'ready' || !card.id || !current) {
      uploads.value = uploads.value.filter((item) => item.key !== card.key)
      return
    }
    try {
      await api.agent.conversations.attachments.remove(current.id, card.id)
    } catch (failure) {
      // 404: o anexo já não existe no servidor, e a ficha pode sair; qualquer outro erro deixa a ficha onde está
      if (!(failure instanceof ApiError && failure.status === 404)) {
        error.value = errorMessage(failure)
        if (failure instanceof ApiError && failure.status === 409) void refreshDetail()
        return
      }
    }
    if (detail.value?.id === current.id) {
      detail.value = {
        ...detail.value,
        pending_attachments: detail.value.pending_attachments.filter((attachment) => attachment.id !== card.id),
      }
    }
  }

  /** Esquece os anexos pendentes de uma conversa vazia que vai servir de rascunho de novo (sem erro na tela se algum falhar). */
  async function discardPending(conversation: AgentConversationDetail): Promise<void> {
    const pending = conversation.pending_attachments
    if (!pending.length) return
    if (detail.value?.id === conversation.id) detail.value = { ...detail.value, pending_attachments: [] }
    await Promise.all(
      pending.map((attachment) =>
        api.agent.conversations.attachments.remove(conversation.id, attachment.id).catch(() => undefined),
      ),
    )
  }

  // ---------- modo, modelo e esforço ----------

  /**
   * Grava no servidor o que a pessoa mudou na conversa aberta. A tela já mostra a escolha; se o servidor recusar, volta
   * ao que estava (e diz por quê). A resposta traz o que o servidor ajustou (trocar de modelo limpa o esforço que o novo não tem).
   */
  async function patchOpen(patch: AgentConversationPatch, expected: Partial<AgentConversationDetail>): Promise<void> {
    const before = detail.value
    if (!before) return
    detail.value = { ...before, ...expected }
    try {
      const updated = await api.agent.conversations.update(before.id, patch)
      if (detail.value?.id === before.id) detail.value = { ...updated, transcript: before.transcript }
      upsertSummary(summaryOf(updated))
    } catch (failure) {
      if (detail.value?.id === before.id) detail.value = before
      error.value = errorMessage(failure)
    }
  }

  async function setMode(next: AgentMode): Promise<void> {
    if (modeLocked.value || next === mode.value) return
    if (detail.value) await patchOpen({ mode: next }, { mode: next })
    else draft.value = { ...draft.value, mode: next }
  }

  async function setModel(name: string): Promise<void> {
    if (!name || busy.value || name === modelName.value) return
    const nextEffort = effortAfterModelChange(effort.value, findModel(models.value?.models, name))
    if (detail.value) await patchOpen({ model: name }, { model: name, effort: nextEffort })
    else draft.value = { ...draft.value, model: name, effort: nextEffort }
  }

  /** `null` volta ao padrão do modelo. */
  async function setEffort(value: string | null): Promise<void> {
    if (value === effort.value) return
    if (detail.value) await patchOpen({ effort: value }, { effort: value })
    else draft.value = { ...draft.value, effort: value }
  }

  /** O contexto, a temperatura e a semente da conversa; o que não vem volta ao padrão. Vale a partir da mensagem seguinte. */
  async function setOptions(next: AgentOptions): Promise<void> {
    const wanted = optionsFrom(valuesOf(next))
    if (sameOptions(wanted, options.value)) return
    if (detail.value) await patchOpen({ options: hasOptions(wanted) ? wanted : null }, { options: wanted })
    else draft.value = { ...draft.value, options: wanted }
  }

  return {
    status,
    models,
    conversations,
    detail,
    items,
    jobId,
    busy,
    stopping,
    stage,
    error,
    attachNotice,
    suggestedModels,
    loaded,
    unloading,
    unloadError,
    engine,
    options,
    attachmentCards,
    pendingCount,
    uploading,
    warnings,
    attachmentsBlock,
    sendable,
    conversationId,
    mode,
    modeLocked,
    modelName,
    effort,
    selectedModel,
    memoryWarning,
    confirmsMemory,
    waitingForYou,
    ready,
    toolsProblem,
    canSend,
    problem,
    init,
    loadStatus,
    loadModels,
    loadLoaded,
    loadConversations,
    unload,
    open,
    startNew,
    send,
    attach,
    removeAttachment,
    stop,
    answerConfirmation,
    rename,
    remove,
    setMode,
    setModel,
    setEffort,
    setOptions,
  }
})

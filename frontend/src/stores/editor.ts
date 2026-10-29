/* O store do editor: o projeto aberto para edição e tudo que as telas do editor compartilham.
   Guarda a spec editável, o "não salvo", a vista de linha do tempo, o cursor, a seleção e a pilha de desfazer.
   As telas nunca falam com a rota de edição direto: leem daqui e mudam por aqui. */
import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import {
  api,
  ApiError,
  errorMessage,
  type EditOperation,
  type OutputFile,
  type SpecDocument,
  type TimelineItem,
  type TimelineView,
  type ValidationSummary,
} from '@/api'
import { SnapshotHistory } from '@/lib/editorHistory'
import { cloneJson, getPath, pruneEmpty, setPath } from '@/lib/editorPaths'
import { completeFocusPair, normalizeSpec } from '@/lib/editorSpec'
import { useToastsStore } from './toasts'
import { useWorkspaceStore } from './workspace'

/** Espera de silêncio antes de recalcular a vista: a cada tecla digitada seria um pedido por caractere. */
export const VIEW_REFRESH_DELAY_MS = 250

export type EditorStatus = 'idle' | 'loading' | 'ready' | 'missing' | 'failed'

/** Um item selecionado na linha do tempo, junto da trilha onde ele está. */
export interface SelectedItem {
  trackId: string
  item: TimelineItem
}

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

export const useEditorStore = defineStore('editor', () => {
  const toasts = useToastsStore()
  const workspace = useWorkspaceStore()

  /* ---------- o projeto aberto ---------- */

  const name = ref<string | null>(null)
  const status = ref<EditorStatus>('idle')
  const loadError = ref('')
  /** A spec em edição. Muda sempre por `setField`, `mutate`, `replaceSpec`, `applyOp` ou `undo`/`redo`. */
  const spec = ref<SpecDocument | null>(null)
  /** Os erros de validação da spec que está no disco (o projeto abriu com spec inválida); vazio = a spec vale. */
  const specErrors = ref<string[]>([])
  /** A fotografia (JSON) do que está salvo: "não salvo" é a spec atual ser diferente dela. */
  const savedJson = ref('')
  const saving = ref(false)
  const saveError = ref('')
  const outputs = ref<OutputFile[]>([])
  const captionsExists = ref(false)
  const validation = ref<ValidationSummary | null>(null)

  /* ---------- vista, cursor e seleção ---------- */

  const view = shallowRef<TimelineView | null>(null)
  const viewError = ref('')
  const viewBusy = ref(false)
  /** Posição do cursor na linha do tempo, em segundos. */
  const playhead = ref(0)
  /** Ids (`TimelineItem.id`) dos itens selecionados. */
  const selection = ref<string[]>([])

  /* ---------- listas de referência ---------- */

  const schema = shallowRef<Record<string, unknown> | null>(null)
  /** Os nomes das transições do catálogo (o schema não as lista). */
  const transitions = ref<string[]>([])
  const referenceError = ref('')

  /* ---------- desfazer e refazer ---------- */

  const history = new SnapshotHistory()
  // a pilha não é reativa; este contador faz `canUndo` e `canRedo` reavaliarem a cada passo
  const historyVersion = ref(0)
  // enquanto a pessoa digita no mesmo campo, tudo é um passo só do desfazer
  let coalescedPath: string | null = null

  let openGeneration = 0
  // aberto com spec inválida, o servidor não deu as saídas nem as legendas: depois de salvar é preciso pedir
  let detailsStale = false
  let viewTicket = 0
  let viewTimer: ReturnType<typeof setTimeout> | null = null
  let referenceLoading: Promise<void> | null = null
  let opChain: Promise<unknown> = Promise.resolve()

  /* ---------- derivados ---------- */

  const currentJson = computed(() => (spec.value ? JSON.stringify(spec.value) : ''))
  const dirty = computed(() => status.value === 'ready' && spec.value !== null && currentJson.value !== savedJson.value)
  const canUndo = computed(() => historyVersion.value >= 0 && history.canUndo)
  const canRedo = computed(() => historyVersion.value >= 0 && history.canRedo)
  /** Os itens selecionados que ainda existem na vista, com a trilha de cada um. */
  const selectedItems = computed<SelectedItem[]>(() => {
    const wanted = new Set(selection.value)
    if (wanted.size === 0 || !view.value) return []
    return view.value.tracks.flatMap((track) =>
      track.items.filter((item) => wanted.has(item.id)).map((item) => ({ trackId: track.id, item })),
    )
  })
  const total = computed(() => view.value?.total ?? 0)
  /** Cada `src` cru da spec e o caminho absoluto que o servidor resolveu para ele, lidos da vista. */
  const resolvedPaths = computed(() => {
    const map = new Map<string, string>()
    for (const track of view.value?.tracks ?? []) {
      for (const item of track.items) if (item.src && item.path) map.set(item.src, item.path)
    }
    for (const source of Object.values(view.value?.sources ?? {})) if (source.src && source.path) map.set(source.src, source.path)
    return map
  })

  /** Os caminhos (crus e resolvidos) que a vista marcou como ausentes do disco: dali não adianta pedir miniatura. */
  const missingPaths = computed(() => {
    const set = new Set<string>()
    const add = (...paths: Array<string | null | undefined>) => paths.forEach((path) => path && set.add(path))
    for (const track of view.value?.tracks ?? []) {
      for (const item of track.items) if (item.missing) add(item.src, item.path)
    }
    // uma fonte em várias partes não diz qual parte sumiu: só vale quando ela tem um arquivo só
    for (const source of Object.values(view.value?.sources ?? {})) if (source.missing && source.parts.length <= 1) add(source.src, source.path)
    return set
  })

  /* ---------- abrir e fechar ---------- */

  function resetProject(projectName: string | null): void {
    openGeneration += 1
    viewTicket += 1
    if (viewTimer) clearTimeout(viewTimer)
    viewTimer = null
    name.value = projectName
    spec.value = null
    specErrors.value = []
    savedJson.value = ''
    saveError.value = ''
    loadError.value = ''
    outputs.value = []
    captionsExists.value = false
    validation.value = null
    view.value = null
    viewError.value = ''
    viewBusy.value = false
    playhead.value = 0
    selection.value = []
    history.clear()
    historyVersion.value += 1
    coalescedPath = null
    detailsStale = false
    opChain = Promise.resolve()
  }

  /** Os erros da validação do servidor, um por linha, para mostrar ao lado da spec. */
  function errorLines(error: ApiError): string[] {
    return error.message.split('\n').filter(Boolean)
  }

  function adoptSpec(next: SpecDocument): void {
    spec.value = normalizeSpec(cloneJson(next))
    savedJson.value = JSON.stringify(spec.value)
  }

  async function open(projectName: string, options: { force?: boolean } = {}): Promise<void> {
    const alreadyOpen = name.value === projectName && (status.value === 'ready' || status.value === 'loading')
    if (!options.force && alreadyOpen) {
      // voltar ao editor mantém a edição em andamento; só as saídas podem ter mudado fora dele
      if (status.value === 'ready') void reloadDetails()
      return
    }
    resetProject(projectName)
    status.value = 'loading'
    const generation = openGeneration
    void loadReference()
    try {
      const detail = await api.projects.get(projectName)
      if (generation !== openGeneration) return
      adoptSpec(detail.spec as SpecDocument)
      outputs.value = detail.outputs
      captionsExists.value = detail.captions_exists
      status.value = 'ready'
      workspace.openProject(projectName)
      await refreshView()
    } catch (error) {
      if (generation !== openGeneration) return
      const body = error instanceof ApiError ? (error.detail as { raw_spec?: unknown } | null) : null
      if (error instanceof ApiError && error.status === 422 && body && typeof body.raw_spec === 'object' && body.raw_spec) {
        // a spec do disco não passa na validação: abre mesmo assim, para a pessoa consertar no JSON e salvar
        adoptSpec(body.raw_spec as SpecDocument)
        specErrors.value = errorLines(error)
        detailsStale = true
        status.value = 'ready'
        workspace.openProject(projectName)
      } else if (error instanceof ApiError && error.status === 404) {
        status.value = 'missing'
        loadError.value = `Não existe um projeto chamado “${projectName}”.`
      } else {
        status.value = 'failed'
        loadError.value = errorMessage(error)
      }
    }
  }

  function close(): void {
    resetProject(null)
    status.value = 'idle'
  }

  /** Lê de novo as saídas e as legendas do servidor (depois de um render, por exemplo), sem mexer na spec. */
  async function reloadDetails(): Promise<void> {
    const target = name.value
    if (!target) return
    try {
      const detail = await api.projects.get(target)
      if (name.value !== target) return
      outputs.value = detail.outputs
      captionsExists.value = detail.captions_exists
    } catch {
      // a lista fica como estava; a próxima tentativa corrige
    }
  }

  /* ---------- listas de referência ---------- */

  /** Carrega o schema da spec e o catálogo de transições uma vez; os formulários tiram daí as opções. */
  function loadReference(): Promise<void> {
    if (schema.value) return Promise.resolve()
    referenceLoading ??= (async () => {
      const [schemaResult, transitionResult] = await Promise.allSettled([api.editor.schema(), api.transitions.catalog()])
      if (schemaResult.status === 'fulfilled') schema.value = schemaResult.value
      else referenceError.value = errorMessage(schemaResult.reason)
      if (transitionResult.status === 'fulfilled') transitions.value = transitionResult.value.transitions.map((t) => t.name)
    })().finally(() => {
      referenceLoading = null
    })
    return referenceLoading
  }

  /* ---------- editar a spec ---------- */

  function get(path: string): unknown {
    return getPath(spec.value, path)
  }

  function recordHistory(before: string): void {
    history.record(before)
    historyVersion.value += 1
  }

  function afterChange(): void {
    validation.value = null
    scheduleViewRefresh()
  }

  /**
   * Muda um campo por caminho ("timeline.0.speed"). `undefined` apaga o campo (vale o padrão do servidor).
   * Mudanças seguidas no mesmo campo valem um passo só do desfazer.
   */
  function setField(path: string, value: unknown): void {
    if (!spec.value) return
    if (sameValue(getPath(spec.value, path), value)) return
    if (coalescedPath !== path) {
      recordHistory(currentJson.value)
      coalescedPath = path
    }
    setPath(spec.value, path, value)
    completeFocusPair(spec.value, path)
    afterChange()
  }

  /**
   * Muda a spec por uma função (trocar o tipo de um trecho, subir, duplicar, renomear fonte...) e vale um passo do
   * desfazer. Se a função não mudou nada, não registra passo nenhum. Devolve o que a função devolveu.
   */
  function mutate<T>(change: (draft: SpecDocument) => T): T | undefined {
    if (!spec.value) return undefined
    const before = currentJson.value
    const result = change(spec.value)
    if (JSON.stringify(spec.value) === before) return result
    recordHistory(before)
    coalescedPath = null
    afterChange()
    return result
  }

  /** Troca a spec inteira (o "Aplicar" da aba JSON). Vale um passo do desfazer. */
  function replaceSpec(next: SpecDocument): void {
    if (!spec.value) return
    const before = currentJson.value
    const replacement = normalizeSpec(cloneJson(next))
    if (JSON.stringify(replacement) === before) return
    recordHistory(before)
    coalescedPath = null
    spec.value = replacement
    afterChange()
  }

  /* ---------- a vista de linha do tempo ---------- */

  function applyView(next: TimelineView): void {
    view.value = next
    viewError.value = ''
    const ids = new Set(next.tracks.flatMap((track) => track.items.map((item) => item.id)))
    if (selection.value.some((id) => !ids.has(id))) selection.value = selection.value.filter((id) => ids.has(id))
    if (playhead.value > next.total) playhead.value = Math.max(0, next.total)
  }

  /** Recalcula a vista agora, sobre a spec ainda não salva. Falha de spec incompleta só vira aviso, a vista antiga fica. */
  async function refreshView(): Promise<void> {
    if (viewTimer) clearTimeout(viewTimer)
    viewTimer = null
    const target = name.value
    const current = spec.value
    if (!target || !current) return
    const ticket = (viewTicket += 1)
    viewBusy.value = true
    try {
      const next = await api.editor.timeline(target, pruneEmpty(current))
      if (ticket !== viewTicket || name.value !== target) return
      applyView(next)
      // o servidor montou a vista, então a spec vale: os erros de quando o projeto abriu já não se aplicam
      specErrors.value = []
    } catch (error) {
      if (ticket !== viewTicket || name.value !== target) return
      viewError.value = errorMessage(error)
    } finally {
      if (ticket === viewTicket) viewBusy.value = false
    }
  }

  /** Pede a vista nova depois de 250 ms sem mudança. */
  function scheduleViewRefresh(): void {
    if (viewTimer) clearTimeout(viewTimer)
    viewTimer = setTimeout(() => void refreshView(), VIEW_REFRESH_DELAY_MS)
  }

  /* ---------- as operações de edição do servidor ---------- */

  /** Chama o servidor com uma operação e adota a spec e a vista que voltam. Quem chama decide o passo do desfazer. */
  async function callOperation(op: EditOperation, target: string): Promise<boolean> {
    const current = spec.value
    if (name.value !== target || !current) return false
    try {
      const result = await api.editor.edit(target, pruneEmpty(current), op)
      if (name.value !== target) return false
      spec.value = normalizeSpec(result.spec)
      specErrors.value = []
      validation.value = null
      applyView(result.timeline)
      return true
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não foi possível editar', description: errorMessage(error) })
      return false
    }
  }

  /** Roda as operações uma depois da outra; um comando de várias operações vale UM passo do desfazer. */
  async function runOperations(ops: EditOperation[]): Promise<boolean> {
    const target = name.value
    if (!target || !spec.value) return false
    const before = currentJson.value
    let done = 0
    for (const op of ops) {
      if (!(await callOperation(op, target))) break
      done += 1
    }
    // o que já foi feito antes de uma falha continua valendo, e desfazer o devolve inteiro
    if (done > 0 && name.value === target) {
      recordHistory(before)
      coalescedPath = null
    }
    return done === ops.length
  }

  function enqueue(ops: EditOperation[]): Promise<boolean> {
    const run = opChain.then(
      () => runOperations(ops),
      () => runOperations(ops),
    )
    opChain = run
    return run
  }

  /**
   * Aplica uma das dez operações da linha do tempo (cortar, remover, mover, aparar, duplicar, inserir, ajustar uma
   * sobreposição, mudar um campo) pelo servidor. As chamadas entram em fila: cada uma parte da spec que a anterior deixou.
   */
  function applyOp(op: EditOperation): Promise<boolean> {
    return enqueue([op])
  }

  /**
   * Aplica várias operações em sequência como um comando só: remover cinco trechos selecionados é um passo do
   * desfazer, não cinco. Se uma falha, as seguintes não rodam e o que já foi feito fica registrado.
   */
  function applyOps(ops: EditOperation[]): Promise<boolean> {
    return ops.length === 0 ? Promise.resolve(true) : enqueue(ops)
  }

  /** Guarda o resultado da validação do projeto (o cartão na tela do editor); qualquer mudança na spec o apaga. */
  function setValidation(summary: ValidationSummary | null): void {
    validation.value = summary
  }

  /* ---------- salvar ---------- */

  /** Grava a spec no projeto (sem os campos vazios). Devolve se deu certo; o erro fica em `saveError`. */
  async function save(): Promise<boolean> {
    const target = name.value
    const current = spec.value
    if (!target || !current) return false
    saving.value = true
    saveError.value = ''
    const sent = currentJson.value
    try {
      await api.editor.saveProject(target, pruneEmpty(current))
      if (name.value !== target) return true
      savedJson.value = sent
      const wasInvalid = specErrors.value.length > 0 || detailsStale
      specErrors.value = []
      toasts.push({ tone: 'success', title: 'Projeto salvo' })
      if (wasInvalid) {
        detailsStale = false
        await reloadDetails()
        await refreshView()
      }
      return true
    } catch (error) {
      saveError.value = errorMessage(error)
      toasts.push({ tone: 'error', title: 'Não foi possível salvar', description: saveError.value })
      return false
    } finally {
      saving.value = false
    }
  }

  /* ---------- desfazer e refazer ---------- */

  function restore(snapshot: string): void {
    spec.value = normalizeSpec(JSON.parse(snapshot) as SpecDocument)
    coalescedPath = null
    validation.value = null
    historyVersion.value += 1
    void refreshView()
  }

  function undo(): boolean {
    if (!spec.value) return false
    const snapshot = history.undo(currentJson.value)
    if (snapshot === null) return false
    restore(snapshot)
    return true
  }

  function redo(): boolean {
    if (!spec.value) return false
    const snapshot = history.redo(currentJson.value)
    if (snapshot === null) return false
    restore(snapshot)
    return true
  }

  /* ---------- cursor e seleção ---------- */

  function setPlayhead(seconds: number): void {
    const limit = view.value ? view.value.total : Number.POSITIVE_INFINITY
    playhead.value = Math.min(Math.max(0, seconds), limit)
  }

  function select(ids: string[]): void {
    selection.value = [...new Set(ids)]
  }

  function clearSelection(): void {
    selection.value = []
  }

  /** O caminho absoluto de um `src` da spec (que pode ser relativo ao projeto); sem a vista, o próprio `src`. */
  function resolvePath(src: string): string {
    return resolvedPaths.value.get(src) ?? src
  }

  /** O arquivo deste `src` da spec não está no disco, segundo a vista. */
  function isMissing(src: string): boolean {
    return missingPaths.value.has(src) || missingPaths.value.has(resolvePath(src))
  }

  /** O item da vista com este id e a trilha dele. */
  function findItem(id: string): SelectedItem | null {
    for (const track of view.value?.tracks ?? []) {
      const item = track.items.find((candidate) => candidate.id === id)
      if (item) return { trackId: track.id, item }
    }
    return null
  }

  return {
    // projeto
    name,
    status,
    loadError,
    spec,
    specErrors,
    saving,
    saveError,
    outputs,
    captionsExists,
    validation,
    dirty,
    open,
    close,
    reloadDetails,
    setValidation,
    save,
    // listas de referência
    schema,
    transitions,
    referenceError,
    loadReference,
    // edição
    get,
    setField,
    mutate,
    replaceSpec,
    applyOp,
    applyOps,
    // vista
    view,
    viewError,
    viewBusy,
    total,
    refreshView,
    scheduleViewRefresh,
    // desfazer
    canUndo,
    canRedo,
    undo,
    redo,
    // cursor e seleção
    playhead,
    selection,
    selectedItems,
    setPlayhead,
    select,
    clearSelection,
    findItem,
    resolvePath,
    isMissing,
  }
})

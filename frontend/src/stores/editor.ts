/* O store do editor: o projeto aberto para edição e tudo que as telas do editor compartilham.
   Guarda a spec editável, o "não salvo", a vista de linha do tempo, as caixas das sobreposições no quadro, o cursor,
   a seleção, a pilha de desfazer e a revisão do `spec.json` (para não apagar em silêncio o que mudou no disco).
   As telas nunca falam com a rota de edição direto: leem daqui e mudam por aqui. */
import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import {
  api,
  ApiError,
  errorMessage,
  type BoxLayout,
  type EditOperation,
  type OutputFile,
  type SaveConflictBody,
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

/** De quanto em quanto tempo o editor aberto pergunta ao servidor se o `spec.json` mudou no disco. */
export const DISK_CHECK_INTERVAL_MS = 2000

export type EditorStatus = 'idle' | 'loading' | 'ready' | 'missing' | 'failed'

/** Um item selecionado na linha do tempo, junto da trilha onde ele está. */
export interface SelectedItem {
  trackId: string
  item: TimelineItem
}

/** O disco mudou por fora enquanto o editor tinha mudanças suas: a pessoa escolhe entre recarregar e manter a dela. */
export interface DiskConflict {
  /** A revisão que está no disco agora; nula se o projeto deixou de existir. */
  revision: string | null
}

export interface SaveOptions {
  /** Sem o aviso "Projeto salvo": para quem grava a cada gesto e não quer um aviso por gesto. */
  quiet?: boolean
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
  /** A revisão do `spec.json` na última vez que o editor leu ou gravou o disco; vai no `If-Match` do Salvar. */
  const revision = ref<string | null>(null)
  /** Preenchido quando o disco mudou por fora e há mudança não salva (ou o Salvar levou 409): a faixa de escolha. */
  const conflict = ref<DiskConflict | null>(null)
  /** Há um gesto direto em andamento (arrastar, redimensionar): nesse tempo o disco não é consultado. */
  const gesturing = ref(false)

  /* ---------- vista, cursor e seleção ---------- */

  const view = shallowRef<TimelineView | null>(null)
  const viewError = ref('')
  const viewBusy = ref(false)
  /** A caixa de cada sobreposição no quadro, calculada pelo servidor (a mesma conta do render e do QA). */
  const boxes = shallowRef<BoxLayout | null>(null)
  const boxesError = ref('')
  /** Posição do cursor na linha do tempo, em segundos. */
  const playhead = ref(0)
  /** Ids (`TimelineItem.id`) dos itens selecionados. */
  const selection = ref<string[]>([])
  /** O índice (em `spec.overlays`) da sobreposição escolhida no palco ou no inspetor; as duas telas a destacam. */
  const selectedOverlayIndex = ref<number | null>(null)
  /** Sobe a cada pedido para o inspetor mostrar a sobreposição escolhida (abrir a aba, o bloco e o cartão). */
  const overlayReveal = ref(0)

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
  let boxesTicket = 0
  // sobe no começo e no fim de cada gravação: uma consulta de revisão que saiu antes dela vem velha e é descartada
  let writeSerial = 0
  let diskCheckBusy = false
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
  /** A sobreposição escolhida, se ainda existe na spec (remover ou desfazer pode ter tirado o índice). */
  const selectedOverlay = computed<number | null>(() => {
    const index = selectedOverlayIndex.value
    const overlays = spec.value?.overlays
    return index !== null && Array.isArray(overlays) && index < overlays.length ? index : null
  })
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
    boxesTicket += 1
    boxes.value = null
    boxesError.value = ''
    revision.value = null
    conflict.value = null
    gesturing.value = false
    diskCheckBusy = false
    playhead.value = 0
    selection.value = []
    selectedOverlayIndex.value = null
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
      revision.value = detail.revision ?? null
      outputs.value = detail.outputs
      captionsExists.value = detail.captions_exists
      status.value = 'ready'
      workspace.openProject(projectName)
      await refreshView()
    } catch (error) {
      if (generation !== openGeneration) return
      const body = error instanceof ApiError ? (error.detail as { raw_spec?: unknown; revision?: string | null } | null) : null
      if (error instanceof ApiError && error.status === 422 && body && typeof body.raw_spec === 'object' && body.raw_spec) {
        // a spec do disco não passa na validação: abre mesmo assim, para a pessoa consertar no JSON e salvar
        adoptSpec(body.raw_spec as SpecDocument)
        revision.value = body.revision ?? null
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

  /* ---------- digitação em espera ---------- */

  // os campos com atraso (o painel Filtros) guardam o que a pessoa digitou até ela parar; quem lê a spec de verdade
  // (salvar, operar na linha do tempo, desfazer) pede antes para eles gravarem, senão perderia as últimas teclas
  const pendingEdits = new Set<() => void>()

  /** Registra como gravar a digitação que está esperando; devolve como desregistrar. */
  function onPendingEdits(flush: () => void): () => void {
    pendingEdits.add(flush)
    return () => void pendingEdits.delete(flush)
  }

  /** Grava já tudo o que os campos com atraso ainda seguram. */
  function flushPendingEdits(): void {
    for (const flush of [...pendingEdits]) flush()
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
    const body = pruneEmpty(current)
    // as caixas seguem a mesma spec e o mesmo gatilho da vista, mas cada pedido tem o seu fim: um não segura o outro
    void loadBoxes(target, body)
    try {
      const next = await api.editor.timeline(target, body)
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

  /* ---------- as caixas das sobreposições ---------- */

  async function loadBoxes(target: string, body: SpecDocument): Promise<void> {
    const ticket = (boxesTicket += 1)
    try {
      const next = await api.editor.boxes(target, body)
      if (ticket !== boxesTicket || name.value !== target) return
      // uma resposta fora do contrato (servidor antigo) deixa as caixas como estavam
      if (!next || !Array.isArray(next.boxes)) return
      boxes.value = next
      boxesError.value = ''
    } catch (error) {
      if (ticket !== boxesTicket || name.value !== target) return
      // spec incompleta ou servidor sem a rota: as caixas anteriores ficam, e o palco cai na posição aproximada
      boxesError.value = errorMessage(error)
    }
  }

  /** Pede as caixas já, sobre a spec na tela (depois de um gesto, por exemplo), sem esperar o atraso da vista. */
  function refreshBoxes(): Promise<void> {
    const target = name.value
    const current = spec.value
    return target && current ? loadBoxes(target, pruneEmpty(current)) : Promise.resolve()
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
      void refreshBoxes()
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
    flushPendingEdits()
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

  /* ---------- salvar e coerência com o disco ---------- */

  /** Grava a spec no disco (sem os campos vazios) com a revisão dada no `If-Match`. Devolve se deu certo. */
  async function writeSpec(ifMatch: string | null, options: SaveOptions): Promise<boolean> {
    flushPendingEdits()
    const target = name.value
    const current = spec.value
    if (!target || !current) return false
    saving.value = true
    saveError.value = ''
    const sent = currentJson.value
    writeSerial += 1
    try {
      const result = await api.editor.saveProject(target, pruneEmpty(current), ifMatch)
      if (name.value !== target) return true
      savedJson.value = sent
      if (result?.revision) revision.value = result.revision
      conflict.value = null
      const wasInvalid = specErrors.value.length > 0 || detailsStale
      specErrors.value = []
      if (!options.quiet) toasts.push({ tone: 'success', title: 'Projeto salvo' })
      if (wasInvalid) {
        detailsStale = false
        await reloadDetails()
        await refreshView()
      }
      return true
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        // o disco mudou desde a última leitura: nada foi gravado, e quem escolhe é a pessoa (faixa no topo)
        const body = error.detail as SaveConflictBody | null
        if (name.value === target) conflict.value = { revision: body?.revision ?? null }
        return false
      }
      saveError.value = errorMessage(error)
      toasts.push({ tone: 'error', title: 'Não foi possível salvar', description: saveError.value })
      return false
    } finally {
      writeSerial += 1
      saving.value = false
    }
  }

  /** Grava a spec no projeto. Devolve se deu certo; o erro fica em `saveError`, e um 409 (o disco mudou por fora)
   * vira `conflict`, que a tela mostra como escolha. */
  function save(options: SaveOptions = {}): Promise<boolean> {
    return writeSpec(revision.value, options)
  }

  /** "Manter o meu": grava por cima do que mudou no disco, com a revisão nova que o servidor mostrou no conflito. */
  function keepMine(): Promise<boolean> {
    const pending = conflict.value
    return pending ? writeSpec(pending.revision, {}) : save()
  }

  /** Troca a spec da tela pela do disco. Se o conteúdo mudou, a de antes vira um passo do desfazer, e o que não estava
   * salvo ainda pode voltar por ele. Devolve se o conteúdo mudou. */
  function takeDiskSpec(next: SpecDocument, diskRevision: string | null): boolean {
    const before = currentJson.value
    const replacement = normalizeSpec(cloneJson(next))
    const changed = JSON.stringify(replacement) !== before
    if (changed) recordHistory(before)
    spec.value = replacement
    savedJson.value = JSON.stringify(replacement)
    coalescedPath = null
    revision.value = diskRevision ?? revision.value
    conflict.value = null
    validation.value = null
    return changed
  }

  /** Lê o projeto do disco e o adota (descarta o que não estava salvo). O aviso só sai se o conteúdo mudou de fato. */
  async function reloadFromDisk(options: { notice: string; quiet?: boolean }): Promise<boolean> {
    const target = name.value
    if (!target) return false
    const generation = openGeneration
    try {
      let changed: boolean
      let invalid = false
      try {
        const detail = await api.projects.get(target)
        if (generation !== openGeneration) return false
        changed = takeDiskSpec(detail.spec as SpecDocument, detail.revision ?? null)
        specErrors.value = []
        outputs.value = detail.outputs
        captionsExists.value = detail.captions_exists
      } catch (error) {
        const body = error instanceof ApiError ? (error.detail as { raw_spec?: unknown; revision?: string | null } | null) : null
        if (!(error instanceof ApiError && error.status === 422 && body && typeof body.raw_spec === 'object' && body.raw_spec)) throw error
        // o que está no disco não passa na validação: abre para consertar na aba JSON, como na abertura do projeto
        changed = takeDiskSpec(body.raw_spec as SpecDocument, body.revision ?? null)
        specErrors.value = errorLines(error)
        detailsStale = true
        invalid = true
      }
      if (changed) {
        toasts.push({ tone: 'info', title: options.notice, description: 'Desfazer (Ctrl+Z) volta à versão que estava na tela.' })
      }
      // sem vista para uma spec inválida: ela só vem depois que a pessoa a conserta, como ao abrir o projeto
      if (!invalid) await refreshView()
      return true
    } catch (error) {
      if (!options.quiet) {
        toasts.push({ tone: 'error', title: 'Não foi possível recarregar do disco', description: errorMessage(error) })
      }
      return false
    }
  }

  /** "Recarregar do disco": descarta o que não foi salvo e fica com o que o disco tem. */
  function reloadFromConflict(): Promise<boolean> {
    return reloadFromDisk({ notice: 'Projeto recarregado do disco' })
  }

  async function onDiskChanged(onDisk: string): Promise<void> {
    // já há uma escolha na tela: ela só ganha a revisão mais nova, para o "Manter o meu" gravar sobre ela
    if (conflict.value) {
      conflict.value = { revision: onDisk }
      return
    }
    flushPendingEdits()
    if (dirty.value) {
      conflict.value = { revision: onDisk }
      return
    }
    // se não deu para ler o disco, a escolha vai para a tela em vez de um erro a cada consulta
    const reloaded = await reloadFromDisk({ notice: 'O projeto foi atualizado fora do editor', quiet: true })
    if (!reloaded && name.value) conflict.value = { revision: onDisk }
  }

  /**
   * Pergunta ao servidor qual é a revisão do `spec.json` e reage se ela não é a que o editor conhece: sem nada por
   * salvar recarrega sozinho; com mudança não salva abre a escolha. Não consulta durante um gesto nem uma gravação, e
   * descarta a resposta que saiu antes de uma gravação nossa (ela traria a revisão de antes dela).
   */
  async function checkDisk(): Promise<void> {
    const target = name.value
    if (!target || status.value !== 'ready' || diskCheckBusy || saving.value || gesturing.value) return
    diskCheckBusy = true
    const serial = writeSerial
    const generation = openGeneration
    try {
      const answer = await api.editor.revision(target)
      if (generation !== openGeneration || serial !== writeSerial || saving.value || gesturing.value) return
      const onDisk = answer?.revision
      if (typeof onDisk !== 'string' || onDisk === revision.value) return
      // sem revisão conhecida (servidor antigo na abertura): a primeira vista não é uma mudança por fora
      if (revision.value === null) {
        revision.value = onDisk
        return
      }
      await onDiskChanged(onDisk)
    } catch {
      // sem resposta agora (servidor ocupado, projeto sumiu): a próxima consulta tenta de novo
    } finally {
      diskCheckBusy = false
    }
  }

  /** Um gesto direto começa: o disco não é consultado até ele acabar. */
  function beginGesture(): void {
    gesturing.value = true
  }

  function endGesture(): void {
    gesturing.value = false
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
    flushPendingEdits()
    if (!spec.value) return false
    const snapshot = history.undo(currentJson.value)
    if (snapshot === null) return false
    restore(snapshot)
    return true
  }

  function redo(): boolean {
    flushPendingEdits()
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

  /** Escolhe a sobreposição de índice `index` (ou nenhuma). Com `reveal`, o inspetor abre nela; é o que o clique numa
   * caixa do palco pede. */
  function selectOverlay(index: number | null, options: { reveal?: boolean } = {}): void {
    selectedOverlayIndex.value = index
    if (index !== null && options.reveal) overlayReveal.value += 1
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
    /** A spec em edição como texto: muda a cada mudança dela, para quem só quer saber se algo mudou. */
    specJson: currentJson,
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
    // coerência com o disco
    revision,
    conflict,
    gesturing,
    keepMine,
    reloadFromConflict,
    checkDisk,
    beginGesture,
    endGesture,
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
    onPendingEdits,
    flushPendingEdits,
    // vista
    view,
    viewError,
    viewBusy,
    total,
    refreshView,
    scheduleViewRefresh,
    // caixas das sobreposições
    boxes,
    boxesError,
    refreshBoxes,
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
    selectedOverlay,
    overlayReveal,
    selectOverlay,
    findItem,
    resolvePath,
    isMissing,
  }
})

/* O que o player precisa do servidor além da linha do tempo: o tema da marca (cores, fonte e logos do texto), os
   proxies leves dos vídeos e a mixagem de áudio da prévia.

   A mixagem é feita no servidor com o mesmo grafo de áudio do render e tocada num `<audio>` só. Depois de cada
   edição ela fica velha até a nova ficar pronta, e nesse intervalo o som sai ao vivo, por trilha, com o aviso
   "áudio aproximado". Quem decide qual dos dois soa é `current`. */
import { defineStore } from 'pinia'
import { computed, effectScope, ref, shallowRef, watch, type EffectScope } from 'vue'
import { api, errorMessage, type PreviewAudioStatus, type ProjectTheme, type ProxyEntry } from '@/api'
import { pruneEmpty } from '@/lib/editorPaths'
import { useEditorStore } from './editor'

/** Espera de silêncio depois da última edição antes de pedir a mixagem nova. */
export const MIX_REQUEST_DELAY_MS = 600
/** De quanto em quanto tempo se pergunta se a mixagem ficou pronta. */
export const MIX_POLL_MS = 700
/** Quanto se espera por uma mixagem antes de desistir de perguntar. */
export const MIX_GIVE_UP_MS = 15 * 60 * 1000
export const PROXY_POLL_MS = 2000

export type MixState = 'idle' | 'building' | 'ready' | 'failed'

export const usePlayerMediaStore = defineStore('playerMedia', () => {
  const editor = useEditorStore()

  /* ---------- tema ---------- */

  const theme = shallowRef<ProjectTheme | null>(null)

  /* ---------- proxies ---------- */

  const proxies = ref<ProxyEntry[]>([])
  const proxyBuilding = ref(false)
  const proxyNotice = ref('')
  const proxyUrls = computed<Record<string, string>>(() =>
    Object.fromEntries(proxies.value.filter((entry) => entry.ready && entry.url).map((entry) => [entry.src, entry.url as string])),
  )
  const proxiesReady = computed(() => proxies.value.filter((entry) => entry.ready).length)
  const proxiesMissing = computed(() => proxies.value.filter((entry) => entry.missing).length)
  const proxiesPending = computed(() => proxies.value.filter((entry) => !entry.ready && !entry.missing).length)

  /* ---------- a mixagem do áudio ---------- */

  const mixState = ref<MixState>('idle')
  /** A chave da mixagem da spec de agora, assim que o servidor responde. */
  const latestKey = ref<string | null>(null)
  /** A última mixagem pronta (a chave e o endereço): fica tocando até a nova chegar? Não: só vale se for a atual. */
  const readyKey = ref<string | null>(null)
  const mixUrl = ref<string | null>(null)
  const mixLabel = ref('')
  const mixPercent = ref(0)
  const mixWarnings = ref<string[]>([])
  const mixError = ref('')
  /** Desde que a spec mudou até o servidor dizer a chave nova: a mixagem que se tem pode estar velha. */
  const stale = ref(false)

  /** A mixagem pronta vale para a spec de agora: o `<audio>` toca ela e o som ao vivo cala. */
  const current = computed(
    () => !stale.value && !!mixUrl.value && readyKey.value !== null && readyKey.value === latestKey.value,
  )
  /** O som é o ao vivo: falta a mixagem (abrindo, editando ou com erro). Mostra "áudio aproximado". */
  const approximate = computed(() => !current.value)

  let scope: EffectScope | null = null
  let mixTicket = 0
  let mixTimer: ReturnType<typeof setTimeout> | null = null
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let proxyTimer: ReturnType<typeof setTimeout> | null = null
  let freshOpen = false
  // o pedido de proxies está a caminho: dois erros de vídeo seguidos não geram dois jobs
  let proxyRequesting = false

  function clearMixTimers(): void {
    if (mixTimer) clearTimeout(mixTimer)
    if (pollTimer) clearTimeout(pollTimer)
    mixTimer = null
    pollTimer = null
  }

  function applyStatus(status: PreviewAudioStatus): void {
    latestKey.value = status.key
    stale.value = false
    mixLabel.value = status.label
    mixPercent.value = status.percent
    mixWarnings.value = status.warnings
    if (status.state === 'ready') {
      readyKey.value = status.key
      mixUrl.value = status.url
      mixState.value = 'ready'
      mixError.value = ''
    } else if (status.state === 'failed') {
      mixState.value = 'failed'
      mixError.value = status.error ?? 'A mixagem do áudio falhou.'
    } else {
      mixState.value = 'building'
    }
  }

  function pollMix(target: string, key: string, ticket: number, startedAt: number): void {
    pollTimer = setTimeout(async () => {
      if (ticket !== mixTicket || editor.name !== target) return
      try {
        const status = await api.editor.previewAudio.get(target, key)
        if (ticket !== mixTicket || editor.name !== target) return
        applyStatus(status)
        if (status.state === 'building' && Date.now() - startedAt < MIX_GIVE_UP_MS) pollMix(target, key, ticket, startedAt)
      } catch (error) {
        if (ticket !== mixTicket) return
        mixState.value = 'failed'
        mixError.value = errorMessage(error)
      }
    }, MIX_POLL_MS)
  }

  /** Pede ao servidor a mixagem da edição que está na tela e acompanha até ficar pronta. */
  async function requestMix(): Promise<void> {
    const target = editor.name
    const spec = editor.spec
    if (!target || !spec || editor.status !== 'ready' || editor.specErrors.length > 0) return
    clearMixTimers()
    const ticket = (mixTicket += 1)
    try {
      const status = await api.editor.previewAudio.request(target, pruneEmpty(spec))
      if (ticket !== mixTicket || editor.name !== target) return
      applyStatus(status)
      if (status.state === 'building') pollMix(target, status.key, ticket, Date.now())
    } catch (error) {
      if (ticket !== mixTicket) return
      // sem a mixagem o som continua ao vivo; o erro aparece no aviso do player
      stale.value = true
      mixState.value = 'failed'
      mixError.value = errorMessage(error)
    }
  }

  function scheduleMix(delay: number): void {
    if (mixTimer) clearTimeout(mixTimer)
    mixTimer = setTimeout(() => void requestMix(), delay)
  }

  function onSpecChanged(): void {
    if (editor.status !== 'ready') return
    // o pedido em andamento é da edição anterior: a resposta dele não vale mais
    mixTicket += 1
    clearMixTimers()
    // a mixagem que se tem pode não valer mais; o som volta a ser ao vivo até o servidor dizer a chave nova
    stale.value = true
    const delay = freshOpen ? 0 : MIX_REQUEST_DELAY_MS
    freshOpen = false
    scheduleMix(delay)
  }

  /* ---------- tema e proxies ---------- */

  async function loadTheme(target: string): Promise<void> {
    try {
      const next = await api.editor.theme(target)
      if (editor.name === target) theme.value = next
    } catch {
      // sem o tema o texto usa as cores padrão; o render é o que vale
    }
  }

  function clearProxyTimer(): void {
    if (proxyTimer) clearTimeout(proxyTimer)
    proxyTimer = null
  }

  async function loadProxies(): Promise<void> {
    const target = editor.name
    if (!target) return
    try {
      const entries = await api.editor.proxies.get(target)
      if (editor.name !== target) return
      proxies.value = entries
      if (proxiesPending.value === 0) {
        proxyBuilding.value = false
        proxyNotice.value = ''
      } else if (proxyBuilding.value) {
        proxyTimer = setTimeout(() => void loadProxies(), PROXY_POLL_MS)
      }
    } catch {
      // a prévia segue com os originais
    }
  }

  /** Gera em segundo plano os proxies que faltam e vai trocando os endereços à medida que ficam prontos. */
  async function buildProxies(): Promise<void> {
    const target = editor.name
    if (!target || proxyBuilding.value || proxyRequesting) return
    clearProxyTimer()
    proxyRequesting = true
    try {
      const result = await api.editor.proxies.build(target)
      if (editor.name !== target) return
      proxies.value = result.proxies
      if (result.job && proxiesPending.value > 0) {
        proxyBuilding.value = true
        proxyNotice.value = 'Gerando os proxies leves dos vídeos...'
        proxyTimer = setTimeout(() => void loadProxies(), PROXY_POLL_MS)
      }
    } catch (error) {
      proxyNotice.value = errorMessage(error)
    } finally {
      proxyRequesting = false
    }
  }

  /** Um vídeo não abriu no navegador (HEVC, por exemplo): gera os proxies, que ele sabe tocar. */
  function onMediaError(path: string): void {
    if (proxies.value.some((entry) => entry.src === path && entry.missing)) return
    proxyNotice.value = 'Este vídeo não abre no navegador: gerando o proxy leve...'
    void buildProxies()
  }

  /* ---------- ciclo de vida ---------- */

  function resetProject(): void {
    clearMixTimers()
    clearProxyTimer()
    mixTicket += 1
    theme.value = null
    proxies.value = []
    proxyBuilding.value = false
    proxyNotice.value = ''
    mixState.value = 'idle'
    latestKey.value = null
    readyKey.value = null
    mixUrl.value = null
    mixLabel.value = ''
    mixPercent.value = 0
    mixWarnings.value = []
    mixError.value = ''
    stale.value = false
  }

  /** Liga o player ao projeto aberto no editor: carrega o tema e os proxies e passa a pedir a mixagem a cada edição. */
  function start(): void {
    stop()
    scope = effectScope()
    scope.run(() => {
      watch(
        () => [editor.name, editor.status] as const,
        ([name, status]) => {
          resetProject()
          if (!name || status !== 'ready') return
          freshOpen = true
          void loadTheme(name)
          void loadProxies()
        },
        { immediate: true },
      )
      watch(() => editor.spec, onSpecChanged, { deep: true, immediate: true })
    })
  }

  function stop(): void {
    scope?.stop()
    scope = null
    clearMixTimers()
    clearProxyTimer()
  }

  return {
    theme,
    proxies,
    proxyUrls,
    proxyBuilding,
    proxyNotice,
    proxiesReady,
    proxiesMissing,
    proxiesPending,
    mixState,
    mixUrl,
    mixLabel,
    mixPercent,
    mixWarnings,
    mixError,
    latestKey,
    readyKey,
    current,
    approximate,
    start,
    stop,
    requestMix,
    loadProxies,
    buildProxies,
    onMediaError,
  }
})

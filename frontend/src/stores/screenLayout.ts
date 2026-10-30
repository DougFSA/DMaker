/* O layout de tela: onde cada painel do editor fica, o tamanho dos divisores e o que está oculto. O atual fica no
   navegador (na mesma chave e no mesmo formato da interface clássica, que também lê o que a nova gravou); os
   nomeados que a pessoa salva ficam no servidor, em `/api/layouts`. Os seis embutidos moram em `lib/editorLayout`. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, errorMessage } from '@/api'
import {
  DEFAULT_LAYOUT_NAME,
  builtinLayouts,
  clampSize,
  isBuiltinName,
  normalizeLayout,
  sameLayout,
  swapPanels,
  withFullAreas,
  type LayoutPanelId,
  type NormalizedLayout,
  type SizeKey,
} from '@/lib/editorLayout'
import { readStored, writeStored } from '@/lib/storage'
import { useConfirmStore } from './confirm'
import { useToastsStore } from './toasts'

/** A chave onde o layout atual fica; é a mesma da interface clássica. */
export const CURRENT_LAYOUT_KEY = 'dmaker.layout.current'
/** Onde ficavam os painéis ocultos antes de existir o layout de tela (os botões F e M da linha do tempo). */
const LEGACY_HIDDEN_KEY = 'dmaker.editor.hiddenPanels'

interface StoredLayout {
  name: string
  layout: NormalizedLayout
}

function storedCurrent(): StoredLayout | null {
  try {
    const parsed: unknown = JSON.parse(readStored(CURRENT_LAYOUT_KEY) ?? 'null')
    if (!parsed || typeof parsed !== 'object') return null
    const { name, layout } = parsed as { name?: unknown; layout?: unknown }
    return { name: typeof name === 'string' && name ? name : DEFAULT_LAYOUT_NAME, layout: normalizeLayout(layout) }
  } catch {
    return null
  }
}

/** Quem escondeu os filtros ou a mídia antes do layout de tela os quer escondidos ainda: vira o ponto de partida. */
function startingLayout(): StoredLayout {
  const base = builtinLayouts()[DEFAULT_LAYOUT_NAME]!
  try {
    const legacy: unknown = JSON.parse(readStored(LEGACY_HIDDEN_KEY) ?? '[]')
    if (Array.isArray(legacy)) {
      const ids = legacy.filter((id): id is LayoutPanelId => id === 'filters' || id === 'media')
      return { name: DEFAULT_LAYOUT_NAME, layout: { ...base, hidden: [...new Set([...base.hidden, ...ids])] } }
    }
  } catch {
    // o valor antigo não era uma lista: vale o padrão
  }
  return { name: DEFAULT_LAYOUT_NAME, layout: base }
}

export const useScreenLayoutStore = defineStore('screenLayout', () => {
  const toasts = useToastsStore()
  const confirmations = useConfirmStore()

  const initial = storedCurrent() ?? startingLayout()
  const name = ref(initial.name)
  const layout = ref<NormalizedLayout>(initial.layout)
  /** Os layouts que a pessoa salvou, como o servidor os guarda. */
  const saved = ref<Record<string, NormalizedLayout>>({})
  const savedLoaded = ref(false)
  const busy = ref(false)

  const savedNames = computed(() => Object.keys(saved.value).filter((candidate) => !isBuiltinName(candidate)).sort())
  const isBuiltin = computed(() => isBuiltinName(name.value))

  /** O layout que o nome atual designa, sem as mexidas da pessoa depois de escolhê-lo. */
  const reference = computed<NormalizedLayout | null>(
    () => builtinLayouts()[name.value] ?? (saved.value[name.value] ? normalizeLayout(saved.value[name.value]) : null),
  )
  /** A pessoa arrastou painel ou divisor, ou escondeu algo, depois de escolher o layout. */
  const modified = computed(() => (reference.value ? !sameLayout(reference.value, layout.value) : false))

  function persist(): void {
    writeStored(CURRENT_LAYOUT_KEY, JSON.stringify({ name: name.value, layout: layout.value }))
  }

  function apply(next: NormalizedLayout, nextName: string = name.value): void {
    layout.value = next
    name.value = nextName
    persist()
  }

  /** Lê do servidor os layouts salvos; sem resposta, a lista fica vazia e os embutidos continuam valendo. */
  async function loadSaved(): Promise<void> {
    try {
      const answer = await api.editor.layouts.list()
      saved.value = Object.fromEntries(Object.entries(answer.layouts).map(([key, value]) => [key, normalizeLayout(value)]))
    } catch {
      saved.value = {}
    } finally {
      savedLoaded.value = true
    }
  }

  /** Escolhe um layout pelo nome (embutido ou salvo) e o devolve; nome que não existe não muda nada. */
  function choose(target: string): NormalizedLayout | null {
    const found = builtinLayouts()[target] ?? (saved.value[target] ? normalizeLayout(saved.value[target]) : null)
    if (!found) return null
    apply(found, target)
    return found
  }

  function restoreDefault(): NormalizedLayout {
    const base = builtinLayouts()[DEFAULT_LAYOUT_NAME]!
    apply(base, DEFAULT_LAYOUT_NAME)
    return base
  }

  /** Guarda o layout de agora no servidor com o nome dado. Devolve se salvou; o motivo, quando não, vai num aviso. */
  async function saveAs(rawName: string): Promise<boolean> {
    const target = rawName.trim()
    if (!target) return false
    if (isBuiltinName(target)) {
      toasts.push({ tone: 'error', title: 'Esse nome é de um layout embutido', description: 'Escolha outro nome para o seu layout.' })
      return false
    }
    busy.value = true
    try {
      await api.editor.layouts.save(target, layout.value)
      await loadSaved()
      name.value = target
      persist()
      toasts.push({ tone: 'success', title: 'Layout salvo', description: target })
      return true
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não foi possível salvar o layout', description: errorMessage(error) })
      return false
    } finally {
      busy.value = false
    }
  }

  /** Apaga o layout salvo que está em uso (depois de confirmar) e volta ao padrão. Os embutidos não se apagam. */
  async function removeCurrent(): Promise<boolean> {
    const target = name.value
    if (isBuiltinName(target)) {
      toasts.push({ tone: 'error', title: 'Layouts embutidos não podem ser excluídos' })
      return false
    }
    const accepted = await confirmations.ask({
      title: `Excluir o layout “${target}”?`,
      description: 'Ele some da lista de layouts salvos. Os painéis ficam como estão até você escolher outro.',
      confirmLabel: 'Excluir',
      tone: 'danger',
    })
    if (!accepted) return false
    busy.value = true
    try {
      await api.editor.layouts.remove(target)
      await loadSaved()
      restoreDefault()
      toasts.push({ tone: 'success', title: 'Layout excluído', description: target })
      return true
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não foi possível excluir o layout', description: errorMessage(error) })
      return false
    } finally {
      busy.value = false
    }
  }

  /* ---------- mexidas na tela ---------- */

  function isHidden(panel: LayoutPanelId): boolean {
    return layout.value.hidden.includes(panel)
  }

  function setHidden(panel: LayoutPanelId, hide: boolean): void {
    const rest = layout.value.hidden.filter((candidate) => candidate !== panel)
    apply({ ...layout.value, hidden: hide ? [...rest, panel] : rest })
  }

  function toggle(panel: LayoutPanelId): void {
    setHidden(panel, !isHidden(panel))
  }

  /** Troca os dois painéis de encaixe. */
  function swap(a: LayoutPanelId, b: LayoutPanelId): void {
    if (a === b) return
    apply(swapPanels(withFullAreas(layout.value), a, b))
  }

  function setSize(key: SizeKey, value: number): void {
    apply({ ...layout.value, sizes: { ...layout.value.sizes, [key]: clampSize(key, value) } })
  }

  return {
    name,
    layout,
    saved,
    savedLoaded,
    savedNames,
    busy,
    isBuiltin,
    modified,
    loadSaved,
    choose,
    restoreDefault,
    saveAs,
    removeCurrent,
    isHidden,
    setHidden,
    toggle,
    swap,
    setSize,
  }
})

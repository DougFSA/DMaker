/* O catálogo dos efeitos de áudio do servidor, carregado uma vez: o painel "Efeitos de áudio" monta o menu e os
   formulários a partir dele. Falhar ao carregar só tira os formulários; o resto do painel Filtros segue funcionando. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { errorMessage } from '@/api'
import { deleteUserPreset, fetchAudioEffects, fetchUserPresets, saveChainAsMacro, saveUserPreset } from '@/api/audioEffects'
import type {
  AudioEffectCatalog,
  AudioEffectInfo,
  AudioEffectParam,
  AudioEffectPreset,
  AudioEffectSettings,
  AudioEffectTarget,
  MacroScope,
} from '@/api'
import { useToastsStore } from './toasts'

export const useAudioEffectsStore = defineStore('audioEffects', () => {
  const catalog = ref<AudioEffectCatalog | null>(null)
  const error = ref('')
  /** A marca do projeto aberto: as macros dela entram no menu junto com as globais. */
  const brand = ref('')
  let loading: Promise<void> | null = null

  const effects = computed<AudioEffectInfo[]>(() => catalog.value?.effects ?? [])
  const common = computed<AudioEffectParam[]>(() => catalog.value?.common ?? [])
  const targets = computed<AudioEffectTarget[]>(() => catalog.value?.targets ?? [])
  const presets = computed<AudioEffectPreset[]>(() => catalog.value?.presets ?? [])
  const loaded = computed(() => catalog.value !== null)

  /** Os campos comuns a todo efeito (`start`, `end`) pelo nome; é daí que vêm a unidade e o limite do intervalo. */
  function commonParam(name: string): AudioEffectParam | undefined {
    return common.value.find((param) => param.name === name)
  }

  function infoOf(type: string): AudioEffectInfo | undefined {
    return effects.value.find((info) => info.type === type)
  }

  /** Carrega o catálogo uma vez; chamadas ao mesmo tempo dividem o mesmo pedido, e depois de uma falha pede de novo. */
  async function load(): Promise<void> {
    if (catalog.value) return
    loading ??= (async () => {
      try {
        const loadedCatalog = await fetchAudioEffects(undefined, brand.value || undefined)
        // resposta fora do contrato (servidor antigo): trata como falha em vez de quebrar o painel
        if (!loadedCatalog || !Array.isArray(loadedCatalog.effects)) throw new Error('Resposta inesperada do servidor.')
        catalog.value = loadedCatalog
        error.value = ''
      } catch (failure) {
        error.value = errorMessage(failure)
      } finally {
        loading = null
      }
    })()
    await loading
  }

  /** Troca no catálogo só as macros salvas pela pessoa (globais e da marca do projeto) pelas que o servidor tem agora (as embutidas não mudam). */
  async function refreshUserPresets(): Promise<void> {
    if (!catalog.value) return
    const saved = await fetchUserPresets(brand.value || undefined)
    const builtin = (catalog.value.presets ?? []).filter((preset) => preset.origin !== 'user')
    catalog.value = { ...catalog.value, presets: [...builtin, ...saved] }
  }

  /** Diz de que marca é o projeto aberto e traz as macros dela; sem marca, só as globais. Falhar aqui só deixa as macros da marca de fora. */
  async function useBrand(name: string): Promise<void> {
    if (brand.value === name && catalog.value) return
    brand.value = name
    try {
      await refreshUserPresets()
    } catch {
      /* o menu segue com o que já tem; a próxima troca de projeto tenta de novo */
    }
  }

  /** Salva a cadeia com o nome dado (o mesmo nome troca a macro). Devolve a macro, ou null com o motivo num aviso. */
  async function savePreset(label: string, chain: AudioEffectSettings[]): Promise<AudioEffectPreset | null> {
    const toasts = useToastsStore()
    try {
      const saved = await saveUserPreset(label, chain)
      await refreshUserPresets()
      toasts.push({ tone: 'success', title: `Predefinição "${saved.label}" salva`, description: 'Ela aparece em Predefinições e macros, no menu + Efeito.' })
      return saved
    } catch (failure) {
      toasts.push({ tone: 'error', title: 'Não consegui salvar a predefinição', description: errorMessage(failure) })
      return null
    }
  }

  /** "Salvar a cadeia como macro": a cadeia do item `target` do projeto vira uma macro com o nome e o escopo dados. */
  async function saveChain(
    project: string,
    spec: unknown,
    target: string,
    label: string,
    scope: MacroScope,
  ): Promise<AudioEffectPreset | null> {
    const toasts = useToastsStore()
    try {
      const saved = await saveChainAsMacro(project, { spec, target, label, scope })
      await refreshUserPresets()
      const where = scope === 'brand' ? 'dos projetos da marca' : 'de todos os projetos'
      toasts.push({ tone: 'success', title: `Macro "${saved.label}" salva`, description: `Ela vale ${where}, em Predefinições e macros, no menu + Efeito.` })
      return saved
    } catch (failure) {
      toasts.push({ tone: 'error', title: 'Não consegui salvar a macro', description: errorMessage(failure) })
      return null
    }
  }

  /** Apaga uma macro salva pela pessoa (da pasta da marca, quando for dela). Devolve se apagou. */
  async function removePreset(id: string, fromBrand?: string): Promise<boolean> {
    const toasts = useToastsStore()
    try {
      await deleteUserPreset(id, fromBrand)
      await refreshUserPresets()
      return true
    } catch (failure) {
      toasts.push({ tone: 'error', title: 'Não consegui apagar a macro', description: errorMessage(failure) })
      return false
    }
  }

  return { catalog, error, brand, effects, common, targets, presets, loaded, commonParam, infoOf, load, useBrand, savePreset, saveChain, removePreset }
})

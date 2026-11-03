/* O catálogo dos efeitos de áudio do servidor, carregado uma vez: o painel "Efeitos de áudio" monta o menu e os
   formulários a partir dele. Falhar ao carregar só tira os formulários; o resto do painel Filtros segue funcionando. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { errorMessage } from '@/api'
import { fetchAudioEffects } from '@/api/audioEffects'
import type { AudioEffectCatalog, AudioEffectInfo, AudioEffectParam, AudioEffectTarget } from '@/api'

export const useAudioEffectsStore = defineStore('audioEffects', () => {
  const catalog = ref<AudioEffectCatalog | null>(null)
  const error = ref('')
  let loading: Promise<void> | null = null

  const effects = computed<AudioEffectInfo[]>(() => catalog.value?.effects ?? [])
  const common = computed<AudioEffectParam[]>(() => catalog.value?.common ?? [])
  const targets = computed<AudioEffectTarget[]>(() => catalog.value?.targets ?? [])
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
        const loadedCatalog = await fetchAudioEffects()
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

  return { catalog, error, effects, common, targets, loaded, commonParam, infoOf, load }
})

/* O catálogo dos geradores de som do servidor, carregado uma vez: o bloco "Sons gerados" monta o menu e os formulários a
   partir dele. Falhar ao carregar só tira os formulários; o resto do painel Filtros segue funcionando. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { errorMessage } from '@/api'
import { fetchAudioGenerators } from '@/api/audioGenerators'
import type { AudioGeneratorCatalog, AudioGeneratorInfo } from '@/api'

export const useAudioGeneratorsStore = defineStore('audioGenerators', () => {
  const catalog = ref<AudioGeneratorCatalog | null>(null)
  const error = ref('')
  let loading: Promise<void> | null = null

  const generators = computed<AudioGeneratorInfo[]>(() => catalog.value?.generators ?? [])
  const loaded = computed(() => catalog.value !== null)

  function infoOf(type: string): AudioGeneratorInfo | undefined {
    return generators.value.find((info) => info.type === type)
  }

  /** Carrega o catálogo uma vez; chamadas ao mesmo tempo dividem o mesmo pedido, e depois de uma falha pede de novo. */
  async function load(): Promise<void> {
    if (catalog.value) return
    loading ??= (async () => {
      try {
        const loadedCatalog = await fetchAudioGenerators()
        // resposta fora do contrato (servidor antigo): trata como falha em vez de quebrar o painel
        if (!loadedCatalog || !Array.isArray(loadedCatalog.generators)) throw new Error('Resposta inesperada do servidor.')
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

  return { catalog, error, generators, loaded, infoOf, load }
})

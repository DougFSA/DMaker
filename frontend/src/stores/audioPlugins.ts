/* Os plugins de efeito (LV2 e LADSPA) que o servidor achou, carregados uma vez: o menu "+ Efeito" lista os que o ffmpeg
   hospeda, e o campo de um efeito Plugin monta os controles a partir do que o próprio plugin declara. Falhar ao carregar só
   tira os plugins; o resto do painel Filtros segue funcionando. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { errorMessage } from '@/api'
import { fetchAudioPlugins, scanAudioPlugins, setAudioPluginEnabled } from '@/api/audioPlugins'
import type { PluginCatalog, PluginInfo } from '@/api'
import { pluginOf, usablePlugins } from '@/lib/audioPlugins'
import { useToastsStore } from './toasts'

export const useAudioPluginsStore = defineStore('audioPlugins', () => {
  const catalog = ref<PluginCatalog | null>(null)
  const error = ref('')
  const scanning = ref(false)
  let loading: Promise<void> | null = null

  const plugins = computed<PluginInfo[]>(() => catalog.value?.plugins ?? [])
  const usable = computed(() => usablePlugins(plugins.value))
  const loaded = computed(() => catalog.value !== null)

  /** O plugin que um efeito da spec cita (o formato e a referência), ou undefined. */
  function find(effect: { [field: string]: unknown }): PluginInfo | undefined {
    return pluginOf(plugins.value, effect as { format: string; plugin: string })
  }

  function accept(next: PluginCatalog): void {
    // resposta fora do contrato (servidor antigo): trata como falha em vez de quebrar o painel
    if (!next || !Array.isArray(next.plugins)) throw new Error('Resposta inesperada do servidor.')
    catalog.value = next
    error.value = ''
  }

  /** Carrega a lista uma vez; chamadas ao mesmo tempo dividem o mesmo pedido, e depois de uma falha pede de novo. */
  async function load(): Promise<void> {
    if (catalog.value) return
    loading ??= (async () => {
      try {
        accept(await fetchAudioPlugins())
      } catch (failure) {
        error.value = errorMessage(failure)
      } finally {
        loading = null
      }
    })()
    await loading
  }

  /** Varre as pastas de novo (o servidor pergunta o que cada plugin expõe ao ffmpeg: leva alguns segundos). */
  async function scan(): Promise<void> {
    const toasts = useToastsStore()
    scanning.value = true
    try {
      accept(await scanAudioPlugins())
    } catch (failure) {
      toasts.push({ tone: 'error', title: 'Não consegui varrer os plugins', description: errorMessage(failure) })
    } finally {
      scanning.value = false
    }
  }

  /** Habilita ou desabilita um plugin; os efeitos que o usam são pulados no render enquanto ele estiver desligado. */
  async function setEnabled(plugin: PluginInfo, enabled: boolean): Promise<void> {
    const toasts = useToastsStore()
    try {
      const answer = await setAudioPluginEnabled(plugin.id, enabled)
      const changed = answer.plugins[0]
      if (changed && catalog.value) {
        catalog.value = { ...catalog.value, plugins: catalog.value.plugins.map((item) => (item.id === changed.id ? changed : item)) }
      }
    } catch (failure) {
      toasts.push({ tone: 'error', title: 'Não consegui mudar o plugin', description: errorMessage(failure) })
    }
  }

  return { catalog, error, scanning, plugins, usable, loaded, find, load, scan, setEnabled }
})

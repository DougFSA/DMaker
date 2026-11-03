import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import { api, errorMessage, type ModelDownloadResult, type ModelInventory, type ModelStatus } from '@/api'
import { leftoverLine, listPreview, pruneWarning } from '@/lib/models'
import { useConfirmStore } from './confirm'
import { createJobRun, type JobRun } from './jobRun'
import { useToastsStore } from './toasts'

/**
 * Os modelos de IA instalados: o inventário medido pelo servidor, o download de cada modelo (um trabalho por
 * modelo, que sobrevive a trocar de tela) e as exclusões, sempre depois de a pessoa ver o aviso do servidor.
 */
export const useModelsStore = defineStore('models', () => {
  const toasts = useToastsStore()
  const confirmations = useConfirmStore()

  const inventory = ref<ModelInventory | null>(null)
  const loading = ref(false)
  const failure = ref('')

  /** Um download por modelo; a entrada nasce no primeiro clique em Baixar. */
  const downloads = reactive<Record<string, JobRun<ModelDownloadResult>>>({})
  const removing = ref<Record<string, true>>({})
  const pruning = ref(false)

  /** Há algum download rodando: o servidor recusa apagar sobras enquanto isso. */
  const anyDownloading = computed(() => Object.values(downloads).some((run) => run.running))

  /** O modelo está sendo baixado ou apagado: os botões dele esperam. */
  function isBusy(modelId: string): boolean {
    return !!downloads[modelId]?.running || !!removing.value[modelId]
  }

  /** Mede o disco de novo. Um download em andamento não é interrompido. */
  async function load(): Promise<void> {
    loading.value = true
    failure.value = ''
    try {
      inventory.value = await api.models.inventory()
    } catch (error) {
      failure.value = errorMessage(error)
    } finally {
      loading.value = false
    }
  }

  /** Baixa o que falta do modelo (ou continua o que ficou pela metade) e mede o disco quando o job acaba. */
  async function download(model: ModelStatus): Promise<void> {
    if (isBusy(model.id)) return
    const run = (downloads[model.id] ??= createJobRun<ModelDownloadResult>())
    const result = await run.run(() => api.models.download(model.id))
    await load()
    if (result) toasts.push({ tone: 'success', title: 'Modelo baixado', description: model.name })
  }

  /** Mostra o que apagar o modelo leva embora e quais funções param, e só apaga se a pessoa confirmar. */
  async function remove(model: ModelStatus): Promise<void> {
    if (isBusy(model.id)) return
    removing.value = { ...removing.value, [model.id]: true }
    let measureAgain = true
    try {
      const plan = await api.models.removal(model.id)
      const accepted = await confirmations.ask({
        title: `Apagar ${model.name}?`,
        description: `Pasta e arquivos em cache/models: ${listPreview(plan.paths)}.`,
        warning: plan.warning,
        confirmLabel: 'Apagar',
        tone: 'danger',
      })
      if (!accepted) {
        measureAgain = false
        return
      }
      const { removed } = await api.models.remove(model.id, true)
      toasts.push({ tone: 'success', title: 'Modelo apagado', description: `${model.name}: liberou ${removed.freed_label}.` })
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui apagar o modelo', description: errorMessage(error) })
    } finally {
      const others = { ...removing.value }
      delete others[model.id]
      removing.value = others
      if (measureAgain) await load()
    }
  }

  /** Apaga as sobras que a pessoa está vendo na lista (e só elas), depois de confirmar. */
  async function prune(): Promise<void> {
    const leftovers = inventory.value?.leftovers ?? []
    if (!inventory.value || leftovers.length === 0 || pruning.value) return
    const accepted = await confirmations.ask({
      title: 'Apagar sobras?',
      description: `Itens: ${listPreview(leftovers.map(leftoverLine))}.`,
      warning: pruneWarning(inventory.value),
      confirmLabel: 'Apagar sobras',
      tone: 'danger',
    })
    if (!accepted) return
    pruning.value = true
    try {
      const { removed } = await api.models.prune(
        true,
        leftovers.map((item) => item.path),
      )
      toasts.push({ tone: 'success', title: 'Sobras apagadas', description: `Liberou ${removed.freed_label}.` })
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui apagar as sobras', description: errorMessage(error) })
    } finally {
      pruning.value = false
      await load()
    }
  }

  return { inventory, loading, failure, downloads, removing, pruning, anyDownloading, isBusy, load, download, remove, prune }
})

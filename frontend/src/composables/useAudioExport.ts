import { ref } from 'vue'
import { api, ApiError, errorMessage, type AudioExportConflict, type AudioExportRequest } from '@/api'
import { conflictQuestion } from '@/lib/audioExport'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useConfirm } from './useConfirm'

/** Os arquivos que já existem, quando o 409 da exportação os traz; senão `null`. */
function conflictOf(error: unknown): AudioExportConflict | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  // `ApiError.detail` é o corpo da resposta inteiro; o FastAPI põe o que mandamos dentro de `detail`
  const body = error.detail as { detail?: Partial<AudioExportConflict> } | null
  const detail = body?.detail
  return detail && Array.isArray(detail.existing) ? { message: detail.message ?? '', existing: detail.existing } : null
}

/**
 * Inicia a exportação de áudio de um projeto. O servidor nunca troca um arquivo que já existe sem um sim: ele devolve
 * 409 com a lista, a pessoa confirma aqui e o pedido sai de novo com `overwrite`. Devolve `true` se o job começou.
 */
export function useAudioExport() {
  const jobs = useJobsStore()
  const toasts = useToastsStore()
  const confirm = useConfirm()
  const starting = ref(false)

  async function start(project: string, request: AudioExportRequest): Promise<boolean> {
    starting.value = true
    try {
      let jobId: string
      try {
        jobId = (await api.projects.exportAudio(project, request)).job_id
      } catch (error) {
        const conflict = conflictOf(error)
        if (!conflict) throw error
        const replace = await confirm({
          title: 'Substituir os arquivos?',
          description: conflictQuestion(conflict.existing),
          tone: 'danger',
          confirmLabel: 'Substituir',
        })
        if (!replace) return false
        jobId = (await api.projects.exportAudio(project, { ...request, overwrite: true })).job_id
      }
      jobs.track(jobId, { project, description: `${project}: áudio (${request.mode})` })
      toasts.push({ tone: 'info', title: 'Exportação de áudio iniciada', description: 'O andamento aparece na barra superior.' })
      return true
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não foi possível exportar o áudio', description: errorMessage(error) })
      return false
    } finally {
      starting.value = false
    }
  }

  return { start, starting }
}

import { onScopeDispose } from 'vue'
import type { Router } from 'vue-router'
import { batchResultOf } from '@/lib/batches'
import { useJobsStore, type JobView } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'

/** Avisa com um Toast quando um job termina, em qualquer tela: quem foi para as Saídas ou para outro projeto
 * enquanto o render rodava não precisa ficar olhando a TopBar. */
export function useJobNotifications(router: Router): void {
  const jobs = useJobsStore()
  const toasts = useToastsStore()

  const stop = jobs.onJobEnd((job: JobView) => {
    const batch = job.status === 'done' ? batchResultOf(job.result) : null
    if (batch?.status === 'paused') {
      // o lote parou a pedido (ou sobrou vídeo pendente): não é conclusão nem falha
      toasts.push({
        tone: 'info',
        title: 'Lote pausado',
        description: `${batch.name}: ${batch.summary}`,
        action: { label: 'Ver lote', run: () => void router.push({ name: 'batch' }) },
      })
    } else if (batch) {
      toasts.push({
        tone: batch.failed > 0 ? 'error' : 'success',
        title: batch.failed > 0 ? 'Lote concluído com falhas' : 'Lote concluído',
        description: `${batch.name}: ${batch.summary}`,
        action: { label: 'Ver lote', run: () => void router.push({ name: 'batch' }) },
      })
    } else if (job.status === 'done') {
      toasts.push({
        tone: 'success',
        title: 'Concluído',
        description: job.description,
        action: { label: 'Ver saídas', run: () => void router.push({ name: 'outputs' }) },
      })
    } else {
      toasts.push({
        tone: 'error',
        title: 'O job falhou',
        description: `${job.description}\n${job.error?.split('\n')[0] ?? ''}`.trim(),
      })
    }
  })
  onScopeDispose(stop)
}

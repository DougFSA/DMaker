import { onScopeDispose } from 'vue'
import type { Router } from 'vue-router'
import { batchResultOf } from '@/lib/batches'
import { announcesItself, isAgentTurn, jobDestination } from '@/lib/jobDestination'
import { useJobsStore, type JobView } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'

/** Avisa com um Toast quando um job termina, em qualquer tela: quem foi para as Saídas ou para outro projeto
 * enquanto o render rodava não precisa ficar olhando a TopBar. */
export function useJobNotifications(router: Router): void {
  const jobs = useJobsStore()
  const toasts = useToastsStore()

  const stop = jobs.onJobEnd((job: JobView) => {
    // quem está na tela Agente já vê o fim do turno (a resposta, o erro ou "interrompida"): o aviso só repetiria
    if (isAgentTurn(job) && router.currentRoute.value.name === 'agent') return
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
      // o download de modelo já avisa pela tela dele ("Modelo baixado"): um segundo aviso só repetiria
      if (announcesItself(job)) return
      const destination = jobDestination(job)
      toasts.push({
        tone: 'success',
        title: 'Concluído',
        description: job.description,
        // só quem gerou vídeo leva às Saídas; os outros levam à tela que disparou o job
        action: destination ? { label: destination.label, run: () => void router.push(destination.to) } : undefined,
      })
    } else if (job.status === 'cancelled') {
      // parar a pedido (a narração, por exemplo) não é falha: o que já saiu ficou guardado
      toasts.push({ tone: 'info', title: 'Parado', description: job.description })
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

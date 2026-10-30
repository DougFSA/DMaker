/* Um trabalho que a tela dispara e espera (isolar a voz, transcrever, corrigir, dublar): o que a tela precisa mostrar
   enquanto ele roda (etapa, porcentagem, relógio e as últimas linhas do log) e o que ela precisa saber quando ele
   acaba (resultado, erro ou "parou a pedido"). Vive dentro de uma store para o andamento sobreviver a trocar de aba. */
import { reactive, ref } from 'vue'
import { errorMessage, followJob, isJobCancelled, type FollowedJob, type JobStartResponse } from '@/api'

/** Enquanto o servidor não diz nada, o trabalho está na fila (um só trabalho pesado de voz roda por vez). */
export const QUEUED_LABEL = 'Na fila...'
const LOG_LIMIT = 6

export function createJobRun<T>() {
  const running = ref(false)
  const label = ref('')
  const percent = ref<number | null>(null)
  const startedAtMs = ref<number | null>(null)
  const log = ref<string[]>([])
  const error = ref('')
  const cancelled = ref(false)
  const cancelling = ref(false)
  let followed: FollowedJob<T> | null = null

  /**
   * Inicia o trabalho (`start` faz o POST que devolve o `job_id`) e espera o fim. Devolve o resultado, ou `null`
   * se falhou (o texto fica em `error`) ou parou a pedido (`cancelled`). Um segundo pedido durante o primeiro é ignorado.
   * Se o `start` devolve `null`, a pessoa desistiu antes de o trabalho começar (disse "não" a uma pergunta): nada rodou,
   * então não há erro nem "parado" a mostrar.
   */
  async function run(start: () => Promise<JobStartResponse | null>): Promise<T | null> {
    if (running.value) return null
    running.value = true
    label.value = QUEUED_LABEL
    percent.value = null
    startedAtMs.value = Date.now()
    log.value = []
    error.value = ''
    cancelled.value = false
    cancelling.value = false
    try {
      const started = await start()
      if (!started) {
        label.value = ''
        startedAtMs.value = null
        return null
      }
      followed = followJob<T>(started.job_id, {
        onProgress(progress) {
          if (progress.label) label.value = progress.label
          percent.value = progress.percent ?? null
        },
        onLog(message) {
          // uma linha de log ("Aguardando outro trabalho de voz terminar") diz mais que a etapa velha
          label.value = message
          log.value = [...log.value, message].slice(-LOG_LIMIT)
        },
      })
      return await followed.result
    } catch (failure) {
      if (isJobCancelled(failure)) cancelled.value = true
      else error.value = errorMessage(failure)
      return null
    } finally {
      running.value = false
      cancelling.value = false
      followed = null
    }
  }

  /** Pede ao servidor que pare o trabalho; `run` termina com `cancelled` quando ele de fato parar. */
  async function cancel(): Promise<void> {
    if (!followed || cancelling.value) return
    cancelling.value = true
    try {
      await followed.cancel()
    } catch (failure) {
      cancelling.value = false
      error.value = errorMessage(failure)
    }
  }

  /** Esquece o último trabalho (erro e "parou") sem mexer no que está rodando. */
  function clear(): void {
    if (running.value) return
    error.value = ''
    cancelled.value = false
    label.value = ''
    percent.value = null
    log.value = []
  }

  return reactive({ running, label, percent, startedAtMs, log, error, cancelled, cancelling, run, cancel, clear })
}

export type JobRun<T> = ReturnType<typeof createJobRun<T>>

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type JobEvent, type JobProgress, type JobSnapshot, type JobStatus } from '@/api'

/** Um job de segundo plano como a interface o enxerga: o snapshot do servidor mais o que veio pelo SSE. */
export interface JobView {
  id: string
  description: string
  status: JobStatus
  project: string | null
  progress: JobProgress | null
  startedAtMs: number
  finishedAtMs: number | null
  error: string | null
  log: string[]
  /** Resultado do job (ex.: o RenderResult), só chega pelo evento final do SSE. */
  result: unknown
}

export type JobEndListener = (job: JobView) => void

const POLL_INTERVAL_MS = 3000
const LOG_LIMIT = 200
const PENDING_DESCRIPTION = 'Iniciando'

function hasProgress(progress: JobProgress | undefined): progress is JobProgress {
  return !!progress && Object.keys(progress).length > 0
}

export const useJobsStore = defineStore('jobs', () => {
  const jobs = ref<Record<string, JobView>>({})
  /** false quando a última consulta à API falhou: a TopBar avisa que o servidor sumiu. */
  const reachable = ref(true)

  const sources = new Map<string, EventSource>()
  const endListeners = new Set<JobEndListener>()
  let pollTimer: ReturnType<typeof setInterval> | null = null

  const list = computed(() =>
    Object.values(jobs.value).sort((a, b) => {
      const byState = Number(b.status === 'running') - Number(a.status === 'running')
      return byState || b.startedAtMs - a.startedAtMs
    }),
  )
  const running = computed(() => list.value.filter((job) => job.status === 'running'))
  const runningCount = computed(() => running.value.length)
  const finishedCount = computed(() => list.value.length - running.value.length)

  function forProject(name: string): JobView[] {
    return list.value.filter((job) => job.project === name)
  }

  /** Avisa quando um job que a interface viu rodando termina (ex.: atualizar a lista de saídas). */
  function onJobEnd(listener: JobEndListener): () => void {
    endListeners.add(listener)
    return () => endListeners.delete(listener)
  }

  function closeSource(id: string): void {
    sources.get(id)?.close()
    sources.delete(id)
  }

  function finish(job: JobView, status: JobStatus, error: string | null, result: unknown): void {
    // pode chegar pelo SSE e pela consulta periódica: só a primeira passagem para "terminado" conta
    if (job.status !== 'running') return
    job.status = status
    job.error = error
    job.result = result
    job.finishedAtMs = Date.now()
    if (status === 'done' && job.progress) job.progress = { ...job.progress, percent: 100 }
    closeSource(job.id)
    for (const listener of endListeners) listener(job)
  }

  function applyEvent(id: string, event: JobEvent): void {
    const job = jobs.value[id]
    if (!job) return
    switch (event.kind) {
      case 'start':
        // o servidor reenvia todos os eventos ao reconectar, e todos começam por "start"
        job.log = []
        job.description = event.description || job.description
        break
      case 'log':
        job.log = [...job.log, event.message].slice(-LOG_LIMIT)
        break
      case 'progress': {
        const { label, done, total, percent } = event
        job.progress = { label, done, total, percent }
        break
      }
      case 'end':
        finish(job, event.status, event.error, event.result)
        break
    }
  }

  function upsertFromSnapshot(snapshot: JobSnapshot): void {
    const existing = jobs.value[snapshot.job_id]
    if (!existing) {
      jobs.value[snapshot.job_id] = {
        id: snapshot.job_id,
        description: snapshot.description,
        status: snapshot.status,
        project: snapshot.project,
        progress: hasProgress(snapshot.progress) ? snapshot.progress : null,
        startedAtMs: Date.now() - snapshot.elapsed_s * 1000,
        finishedAtMs: snapshot.status === 'running' ? null : Date.now(),
        error: snapshot.error,
        log: [],
        result: null,
      }
      return
    }
    // um job registrado por track() ainda não sabia o projeto nem a descrição
    existing.project ??= snapshot.project
    if (existing.description === PENDING_DESCRIPTION) existing.description = snapshot.description
    if (snapshot.status !== 'running') {
      finish(existing, snapshot.status, snapshot.error, existing.result)
    } else if (!existing.progress && hasProgress(snapshot.progress)) {
      existing.progress = snapshot.progress
    }
  }

  /** Passa a acompanhar um job pelo SSE (progresso e log ao vivo). Chamar de novo é inofensivo. */
  function track(id: string, known: { project?: string; description?: string } = {}): void {
    if (sources.has(id)) return
    if (!jobs.value[id]) {
      jobs.value[id] = {
        id,
        description: known.description ?? PENDING_DESCRIPTION,
        status: 'running',
        project: known.project ?? null,
        progress: null,
        startedAtMs: Date.now(),
        finishedAtMs: null,
        error: null,
        log: [],
        result: null,
      }
    }
    const source = new EventSource(api.jobs.eventsUrl(id))
    sources.set(id, source)
    source.onmessage = (message: MessageEvent<string>) => {
      try {
        applyEvent(id, JSON.parse(message.data) as JobEvent)
      } catch {
        // linha de keep-alive ou JSON quebrado: o próximo evento corrige o estado
      }
    }
    source.onerror = () => {
      // CLOSED = o navegador desistiu de reconectar; a consulta periódica cobre o resto
      if (source.readyState === EventSource.CLOSED) sources.delete(id)
    }
  }

  async function refresh(): Promise<void> {
    let snapshots: JobSnapshot[]
    try {
      snapshots = await api.jobs.list()
      reachable.value = true
    } catch {
      reachable.value = false
      return
    }
    const present = new Set(snapshots.map((snapshot) => snapshot.job_id))
    for (const snapshot of snapshots) upsertFromSnapshot(snapshot)
    for (const snapshot of snapshots) {
      // job criado por fora (CLI, MCP, classica): passa a ter progresso ao vivo também aqui
      if (snapshot.status === 'running') track(snapshot.job_id)
    }
    for (const job of Object.values(jobs.value)) {
      if (job.status !== 'running' && !present.has(job.id)) delete jobs.value[job.id]
    }
  }

  function startPolling(intervalMs: number = POLL_INTERVAL_MS): void {
    if (pollTimer) return
    void refresh()
    pollTimer = setInterval(() => void refresh(), intervalMs)
  }

  function stopPolling(): void {
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
    for (const id of [...sources.keys()]) closeSource(id)
  }

  async function clearFinished(): Promise<void> {
    await api.jobs.clearFinished()
    for (const job of Object.values(jobs.value)) {
      if (job.status !== 'running') delete jobs.value[job.id]
    }
  }

  return {
    jobs,
    reachable,
    list,
    running,
    runningCount,
    finishedCount,
    forProject,
    onJobEnd,
    track,
    refresh,
    startPolling,
    stopPolling,
    clearFinished,
  }
})

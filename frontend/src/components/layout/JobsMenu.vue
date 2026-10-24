<script setup lang="ts">
/* Indicador de jobs ao vivo da TopBar: quantos estão rodando e, ao abrir, o progresso de cada um. */
import { computed } from 'vue'
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui'
import { RouterLink } from 'vue-router'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import { useNow } from '@/composables/useNow'
import { formatClock } from '@/lib/format'
import { errorMessage } from '@/api'
import { useJobsStore, type JobView } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'

const jobs = useJobsStore()
const toasts = useToastsStore()
const now = useNow()

const summary = computed(() => {
  if (!jobs.reachable) return 'Servidor sem resposta'
  if (jobs.runningCount === 0) return 'Nenhum job ativo'
  return jobs.runningCount === 1 ? '1 job em andamento' : `${jobs.runningCount} jobs em andamento`
})

function elapsed(job: JobView): string {
  return formatClock(((job.finishedAtMs ?? now.value) - job.startedAtMs) / 1000)
}

function statusLabel(job: JobView): string {
  return job.status === 'running' ? 'Em andamento' : job.status === 'done' ? 'Concluído' : 'Erro'
}

async function clearFinished(): Promise<void> {
  try {
    await jobs.clearFinished()
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não foi possível limpar a lista', description: errorMessage(error) })
  }
}
</script>

<template>
  <PopoverRoot>
    <PopoverTrigger
      :class="['jobs-pill', { 'is-live': jobs.runningCount > 0, 'is-offline': !jobs.reachable }]"
      aria-label="Jobs em segundo plano"
    >
      <span class="jobs-pill__dot" aria-hidden="true" />
      <span class="jobs-pill__text">{{ summary }}</span>
      <AppIcon name="chevron-down" :size="16" />
    </PopoverTrigger>

    <PopoverPortal>
      <PopoverContent class="jobs-panel" align="end" :side-offset="10">
        <header class="jobs-panel__header">
          <h2 class="jobs-panel__title">Jobs</h2>
          <AppButton v-if="jobs.finishedCount > 0" variant="ghost" size="sm" @click="clearFinished">
            Limpar concluídos
          </AppButton>
        </header>

        <p v-if="jobs.list.length === 0" class="jobs-panel__empty">
          Renders, exportações e outros trabalhos aparecem aqui enquanto rodam.
        </p>

        <ul v-else class="jobs-panel__list">
          <li v-for="job in jobs.list" :key="job.id" class="job">
            <div class="job__top">
              <span class="job__name">{{ job.description }}</span>
              <AppBadge :tone="job.status === 'running' ? 'accent' : job.status === 'done' ? 'success' : 'error'">
                {{ statusLabel(job) }}
              </AppBadge>
            </div>
            <ProgressBar
              v-if="job.status === 'running'"
              :value="job.progress?.percent ?? null"
              :label="`Progresso de ${job.description}`"
            />
            <div class="job__meta">
              <span v-if="job.status === 'running' && job.progress?.label">
                {{ job.progress.label }} {{ job.progress.percent ?? 0 }}%
              </span>
              <span v-else-if="job.status === 'error'" class="job__error">{{ job.error?.split('\n')[0] }}</span>
              <span>{{ elapsed(job) }}</span>
              <RouterLink v-if="job.project" :to="{ name: 'project', params: { name: job.project } }">
                Abrir projeto
              </RouterLink>
            </div>
          </li>
        </ul>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>

<style scoped>
.jobs-pill {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 2.5rem;
  padding: 0.4rem 0.9rem;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-pill);
  background: var(--color-surface);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-soft);
  transition:
    border-color var(--transition),
    color var(--transition);
}

.jobs-pill:hover {
  border-color: var(--color-accent-soft);
  color: var(--color-text);
}

.jobs-pill__dot {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 50%;
  background: var(--color-text-muted);
}

.jobs-pill.is-live {
  border-color: var(--color-accent-soft);
  color: var(--color-text);
}

.jobs-pill.is-live .jobs-pill__dot {
  background: var(--color-accent);
  box-shadow: 0 0 0 0 var(--color-accent);
  animation: pulse 1.6s ease-out infinite;
}

.jobs-pill.is-offline .jobs-pill__dot {
  background: var(--color-error);
}

@keyframes pulse {
  70% {
    box-shadow: 0 0 0 0.45rem transparent;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}
</style>

<style>
.jobs-panel {
  z-index: 70;
  width: min(26rem, calc(100vw - 2rem));
  max-height: min(32rem, calc(100vh - 6rem));
  overflow-y: auto;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

.jobs-panel:focus {
  outline: none;
}

.jobs-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-4) var(--space-2);
}

.jobs-panel__title {
  font-size: var(--text-md);
}

.jobs-panel__empty {
  padding: var(--space-3) var(--space-4) var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.jobs-panel__list {
  margin: 0;
  padding: 0 var(--space-4) var(--space-4);
  list-style: none;
}

.job {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) 0;
  border-top: 1px solid var(--color-border);
}

.job__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.job__name {
  min-width: 0;
  font-size: var(--text-sm);
  font-weight: 500;
  overflow-wrap: anywhere;
}

.job__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}

.job__error {
  color: var(--color-error);
}
</style>

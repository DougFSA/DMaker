<script setup lang="ts">
/* Andamento ao vivo de um job do projeto: barra do comando atual, tempo decorrido e as últimas linhas do log. */
import { computed } from 'vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import { useNow } from '@/composables/useNow'
import { formatClock } from '@/lib/format'
import { renderResultsFromJob } from '@/lib/outputs'
import type { RenderResult } from '@/api'
import type { JobView } from '@/stores/jobs'

const props = defineProps<{ job: JobView }>()
defineEmits<{ play: [result: RenderResult] }>()

const now = useNow()

const elapsed = computed(() => formatClock(((props.job.finishedAtMs ?? now.value) - props.job.startedAtMs) / 1000))
const recentLog = computed(() => props.job.log.slice(-4))
const results = computed(() => (props.job.status === 'done' ? renderResultsFromJob(props.job.result) : []))
const percent = computed(() => props.job.progress?.percent ?? null)
const errorLine = computed(() => props.job.error?.split('\n')[0] ?? '')
</script>

<template>
  <AppCard :title="job.description">
    <template #actions>
      <AppBadge :tone="job.status === 'running' ? 'accent' : job.status === 'done' ? 'success' : 'error'" dot>
        {{ job.status === 'running' ? 'Em andamento' : job.status === 'done' ? 'Concluído' : 'Falhou' }}
      </AppBadge>
    </template>

    <div v-if="job.status === 'running'" class="live">
      <ProgressBar :value="percent" :label="`Progresso de ${job.description}`" />
      <div class="live__meta">
        <span>{{ job.progress?.label || 'Preparando' }}</span>
        <span v-if="percent !== null">{{ percent }}%</span>
        <span class="live__time">{{ elapsed }}</span>
      </div>
    </div>

    <p v-else-if="job.status === 'error'" class="error" role="alert">
      <AppIcon name="alert" :size="18" />
      <span>{{ errorLine || 'O job terminou com erro.' }}</span>
    </p>

    <div v-else class="done">
      <div v-for="result in results" :key="result.output" class="done__item">
        <span>
          {{ result.preset }} · {{ result.resolution }} · {{ formatClock(result.duration_s) }}
        </span>
        <AppButton v-if="result.output_url" size="sm" variant="primary" @click="$emit('play', result)">
          <AppIcon name="play" :size="14" />
          Assistir
        </AppButton>
      </div>
      <p v-if="!results.length" class="done__plain">Terminou em {{ elapsed }}.</p>
      <ul v-for="result in results.filter((item) => item.warnings.length)" :key="result.output" class="warnings">
        <li v-for="warning in result.warnings" :key="warning">{{ warning }}</li>
      </ul>
    </div>

    <ul v-if="recentLog.length" class="log" aria-label="Últimas mensagens">
      <li v-for="(line, index) in recentLog" :key="index">{{ line }}</li>
    </ul>
  </AppCard>
</template>

<style scoped>
.live {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.live__meta {
  display: flex;
  gap: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.live__time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.error {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  color: var(--color-error);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}

.done {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.done__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  font-size: var(--text-sm);
}

.done__plain {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.warnings {
  margin: 0;
  padding: var(--space-3) var(--space-4);
  list-style: none;
  border-radius: var(--radius-md);
  background: var(--color-warning-bg);
  color: var(--color-warning);
  font-size: var(--text-xs);
}

.log {
  margin: var(--space-4) 0 0;
  padding: var(--space-3);
  list-style: none;
  border-radius: var(--radius-sm);
  background: var(--color-bg-soft);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}

.log li {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

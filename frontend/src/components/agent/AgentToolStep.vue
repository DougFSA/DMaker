<script setup lang="ts">
/* Uma ferramenta que o agente chamou: nome, argumentos, andamento ao vivo e o resultado em uma linha. */
import { computed } from 'vue'
import AppBadge, { type BadgeTone } from '@/components/ui/AppBadge.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import { summarizeArguments, type ToolItem } from '@/lib/agent'

const props = defineProps<{ tool: ToolItem }>()

const STATE_TEXT = { running: 'rodando', done: 'pronta', blocked: 'barrada', error: 'com erro' } as const
const STATE_TONE: Record<ToolItem['state'], BadgeTone> = {
  running: 'info',
  done: 'success',
  blocked: 'warning',
  error: 'error',
}

const args = computed(() => summarizeArguments(props.tool.arguments))
</script>

<template>
  <div class="step" :data-state="tool.state">
    <div class="step__head">
      <code class="step__name">{{ tool.name }}</code>
      <AppBadge :tone="STATE_TONE[tool.state]" :dot="tool.state === 'running'">{{ STATE_TEXT[tool.state] }}</AppBadge>
    </div>
    <p v-if="args" class="step__args">{{ args }}</p>
    <ProgressBar
      v-if="tool.state === 'running' && tool.percent !== null"
      class="step__progress"
      :value="tool.percent"
      :label="`Andamento de ${tool.name}`"
    />
    <p v-if="tool.state === 'running' && tool.label" class="step__label">{{ tool.label }}</p>
    <p v-if="tool.detail" class="step__detail">{{ tool.detail }}</p>
  </div>
</template>

<style scoped>
.step {
  display: grid;
  gap: var(--space-1);
  max-width: min(46rem, 100%);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-left-width: 3px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  font-size: var(--text-sm);
}

.step[data-state='running'] {
  border-left-color: var(--color-info);
}

.step[data-state='done'] {
  border-left-color: var(--color-success);
}

.step[data-state='blocked'] {
  border-left-color: var(--color-warning);
}

.step[data-state='error'] {
  border-left-color: var(--color-error);
}

.step__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.step__name {
  font-family: var(--font-mono);
  font-weight: 600;
}

.step__args,
.step__detail,
.step__label {
  color: var(--color-text-soft);
  overflow-wrap: anywhere;
}

.step__args {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}
</style>

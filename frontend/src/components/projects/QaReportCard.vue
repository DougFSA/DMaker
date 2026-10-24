<script setup lang="ts">
import { computed } from 'vue'
import type { QaLevel, QaReport } from '@/api'
import AppBadge, { type BadgeTone } from '@/components/ui/AppBadge.vue'
import AppCard from '@/components/ui/AppCard.vue'
import { formatClock } from '@/lib/format'
import { findingTime, groupFindings, qaCounts, qaVerdict } from '@/lib/qa'

const props = defineProps<{ report: QaReport }>()

const groups = computed(() => groupFindings(props.report))
const verdict = computed(() => qaVerdict(props.report))

const verdictTone: Record<ReturnType<typeof qaVerdict>, BadgeTone> = {
  clean: 'success',
  warnings: 'warning',
  errors: 'error',
}
const verdictLabel: Record<ReturnType<typeof qaVerdict>, string> = {
  clean: 'Tudo certo',
  warnings: 'Com avisos',
  errors: 'Com erros',
}
const levelTone: Record<QaLevel, BadgeTone> = { erro: 'error', aviso: 'warning', info: 'info' }
</script>

<template>
  <AppCard
    title="Conferência de qualidade"
    :subtitle="`${report.preset} · ${formatClock(report.total)} · ${qaCounts(report)}`"
  >
    <template #actions>
      <AppBadge :tone="verdictTone[verdict]" dot>{{ verdictLabel[verdict] }}</AppBadge>
    </template>

    <p v-if="groups.length === 0" class="clean">
      Nenhum problema encontrado nas checagens automáticas desta spec.
    </p>

    <section v-for="group in groups" :key="group.level" class="group">
      <h4 class="group__title">
        <AppBadge :tone="levelTone[group.level]">{{ group.label }}</AppBadge>
        <span>{{ group.findings.length }}</span>
      </h4>
      <ul class="findings">
        <li v-for="(finding, index) in group.findings" :key="index" class="finding">
          <span class="finding__time">{{ findingTime(finding) }}</span>
          <code class="finding__where">{{ finding.where }}</code>
          <span class="finding__message">{{ finding.message }}</span>
        </li>
      </ul>
    </section>

    <details v-if="report.checks.length" class="checks">
      <summary>O que foi conferido</summary>
      <ul>
        <li v-for="check in report.checks" :key="check">{{ check }}</li>
      </ul>
    </details>
  </AppCard>
</template>

<style scoped>
.clean {
  color: var(--color-success);
  font-weight: 500;
}

.group + .group {
  margin-top: var(--space-5);
}

.group__title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.findings {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.finding {
  display: grid;
  grid-template-columns: 3rem minmax(5rem, 9rem) minmax(0, 1fr);
  align-items: baseline;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-sm);
}

.finding:last-child {
  border-bottom: 0;
}

.finding__time {
  font-variant-numeric: tabular-nums;
  color: var(--color-text-muted);
}

.finding__where {
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-soft);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.finding__message {
  overflow-wrap: anywhere;
}

.checks {
  margin-top: var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.checks summary {
  cursor: pointer;
  font-weight: 500;
  color: var(--color-accent-text);
}

.checks ul {
  margin: var(--space-3) 0 0;
  padding-left: var(--space-5);
}
</style>

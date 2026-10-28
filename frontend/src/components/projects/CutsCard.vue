<script setup lang="ts">
/* A lista do que o corte automático removeu (tempo e motivo), para conferir antes de renderizar; cada
   corte pode ser desfeito, e o trecho volta ao projeto. */
import { computed } from 'vue'
import type { CutReport } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppTable from '@/components/ui/AppTable.vue'
import { cutsSummary, formatCutTime, reasonCounts, reasonTone } from '@/lib/cuts'

const props = defineProps<{ report: CutReport; busyId?: number | null }>()
defineEmits<{ undo: [cutId: number] }>()

const subtitle = computed(() => {
  const counts = reasonCounts(props.report.counts)
  return counts ? `${cutsSummary(props.report)} · ${counts}` : cutsSummary(props.report)
})
</script>

<template>
  <AppCard title="Cortes automáticos" :subtitle="subtitle" flush>
    <template #actions>
      <AppBadge tone="accent">intensidade {{ report.intensity }}</AppBadge>
    </template>

    <p class="hint">
      Os tempos são da gravação original. Confira antes de renderizar: “Desfazer” devolve o trecho ao projeto.
    </p>

    <p v-if="report.cuts.length === 0" class="empty">Nada passou do limite para cortar.</p>
    <AppTable v-else caption="Trechos removidos pelo corte automático">
      <thead>
        <tr>
          <th scope="col" class="cell-num">#</th>
          <th scope="col">Na gravação</th>
          <th scope="col" class="cell-num">Duração</th>
          <th scope="col">Motivo</th>
          <th scope="col">Palavras tiradas</th>
          <th scope="col"><span class="visually-hidden">Ações</span></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="cut in report.cuts" :key="cut.id" :class="{ 'is-undone': cut.undone }">
          <td class="cell-num">{{ cut.id }}</td>
          <td class="cell-time">{{ formatCutTime(cut.start_s) }} a {{ formatCutTime(cut.end_s) }}</td>
          <td class="cell-num">{{ cut.duration_s.toFixed(1).replace('.', ',') }} s</td>
          <td>
            <AppBadge :tone="reasonTone(cut.reason)">{{ cut.reason_label }}</AppBadge>
          </td>
          <td class="cell-words">{{ cut.text || '(silêncio)' }}</td>
          <td class="cell-action">
            <AppButton
              size="sm"
              :loading="busyId === cut.id"
              :disabled="cut.undone || (busyId !== null && busyId !== undefined)"
              :aria-label="cut.undone ? `Corte ${cut.id} desfeito` : `Desfazer o corte ${cut.id}`"
              @click="$emit('undo', cut.id)"
            >
              {{ cut.undone ? 'Desfeito' : 'Desfazer' }}
            </AppButton>
          </td>
        </tr>
      </tbody>
    </AppTable>
  </AppCard>
</template>

<style scoped>
.hint,
.empty {
  margin: 0;
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.cell-time {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.cell-words {
  max-width: 22rem;
  overflow-wrap: anywhere;
}

.cell-action {
  text-align: right;
}

tr.is-undone td:not(.cell-action) {
  color: var(--color-text-muted);
  text-decoration: line-through;
}
</style>

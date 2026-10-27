<script setup lang="ts">
import type { ValidationSummary } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppTable from '@/components/ui/AppTable.vue'
import { baseName, formatClock } from '@/lib/format'

defineProps<{ summary: ValidationSummary }>()

/** O backend usa o caminho da fonte como rótulo de imagens e clipes: na tela basta o nome do arquivo. */
function shortLabel(label: string | null): string {
  if (!label) return '-'
  return /[\\/]/.test(label) ? baseName(label) : label
}
</script>

<template>
  <AppCard title="Validação" subtitle="A spec foi lida e o roteiro do vídeo montado, sem renderizar nada.">
    <template #actions>
      <AppBadge :tone="summary.warnings.length ? 'warning' : 'success'" dot>
        {{ summary.warnings.length ? `${summary.warnings.length} avisos` : 'Sem avisos' }}
      </AppBadge>
    </template>

    <dl class="facts">
      <div>
        <dt>Duração total</dt>
        <dd>{{ formatClock(summary.total_s) }}</dd>
      </div>
      <div>
        <dt>Resolução</dt>
        <dd>{{ summary.resolution }}</dd>
      </div>
      <div>
        <dt>Formato</dt>
        <dd>{{ summary.preset }}</dd>
      </div>
      <div>
        <dt>Marca</dt>
        <dd>{{ summary.theme }}</dd>
      </div>
      <div>
        <dt>Trechos</dt>
        <dd>{{ summary.segments.length }}</dd>
      </div>
    </dl>

    <details v-if="summary.segments.length" class="segments">
      <summary>Ver a lista de trechos</summary>
      <AppTable caption="Trechos do projeto">
        <thead>
          <tr>
            <th scope="col" class="cell-num">#</th>
            <th scope="col">Tipo</th>
            <th scope="col">Conteúdo</th>
            <th scope="col" class="cell-num">Duração</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="segment in summary.segments" :key="segment.index">
            <td class="cell-num">{{ segment.index }}</td>
            <td>
              <AppBadge>{{ segment.type }}</AppBadge>
            </td>
            <td class="segment-label" :title="segment.label ?? undefined">{{ shortLabel(segment.label) }}</td>
            <td class="cell-num">{{ segment.duration_s }} s</td>
          </tr>
        </tbody>
      </AppTable>
    </details>

    <ul v-if="summary.warnings.length" class="warnings" aria-label="Avisos da validação">
      <li v-for="warning in summary.warnings" :key="warning">{{ warning }}</li>
    </ul>
  </AppCard>
</template>

<style scoped>
.facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
  gap: var(--space-4);
  margin: 0;
}

.facts dt {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.facts dd {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 600;
}

.segments {
  margin-top: var(--space-5);
}

.segments summary {
  margin-bottom: var(--space-3);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-accent-text);
}

.segment-label {
  max-width: 28rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.warnings {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: var(--space-5) 0 0;
  padding: var(--space-4);
  list-style: none;
  border-radius: var(--radius-md);
  background: var(--color-warning-bg);
  color: var(--color-warning);
  font-size: var(--text-sm);
}
</style>

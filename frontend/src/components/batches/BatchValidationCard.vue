<script setup lang="ts">
/* O que a validação achou na planilha, antes de renderizar qualquer coisa: como as colunas casaram com o
   modelo e, linha por linha, o que está errado (coluna e motivo). */
import { computed } from 'vue'
import type { BatchValidation } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppTable from '@/components/ui/AppTable.vue'
import { errorsOf, issueText, warningsOf } from '@/lib/batches'

const props = defineProps<{ validation: BatchValidation }>()

const matched = computed(() => Object.entries(props.validation.columns.matched))
const sheetErrors = computed(() => errorsOf(props.validation.issues))
const sheetWarnings = computed(() => warningsOf(props.validation.issues))
</script>

<template>
  <AppCard title="Conferência da planilha" subtitle="Nada foi renderizado: isto é só a validação.">
    <template #actions>
      <AppBadge :tone="validation.ok ? 'success' : validation.invalid > 0 ? 'warning' : 'error'" dot>
        {{ validation.valid }} de {{ validation.total }} {{ validation.total === 1 ? 'linha válida' : 'linhas válidas' }}
      </AppBadge>
    </template>

    <p v-if="matched.length" class="columns">
      <span class="columns__label">Colunas usadas</span>
      <span v-for="[param, header] in matched" :key="param" class="chip">
        {{ header }} <span class="chip__arrow" aria-hidden="true">→</span> {{ param }}
      </span>
    </p>

    <ul v-if="sheetErrors.length" class="notes notes--error" aria-label="Problemas da planilha">
      <li v-for="issue in sheetErrors" :key="issue.message">
        <AppIcon name="alert" :size="16" />
        <span>{{ issueText(issue) }}</span>
      </li>
    </ul>
    <ul v-if="sheetWarnings.length" class="notes notes--warning" aria-label="Avisos da planilha">
      <li v-for="issue in sheetWarnings" :key="issue.message">
        <AppIcon name="info" :size="16" />
        <span>{{ issueText(issue) }}</span>
      </li>
    </ul>

    <AppTable caption="Linhas da planilha e o que a validação achou em cada uma">
      <thead>
        <tr>
          <th scope="col" class="cell-num">Linha</th>
          <th scope="col">Nome do vídeo</th>
          <th scope="col">Situação</th>
          <th scope="col">O que achei</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in validation.rows" :key="row.index" :class="{ 'row--bad': !row.valid }">
          <td class="cell-num">{{ row.line }}</td>
          <td class="cell-name">{{ row.title || '(sem nome)' }}</td>
          <td>
            <AppBadge v-if="!row.valid" tone="error" dot>Com problema</AppBadge>
            <AppBadge v-else-if="warningsOf(row.issues).length" tone="warning" dot>Com aviso</AppBadge>
            <AppBadge v-else tone="success" dot>Pronta</AppBadge>
          </td>
          <td>
            <ul v-if="row.issues.length" class="issues">
              <li v-for="issue in row.issues" :key="issue.message + issue.field" :class="`issue--${issue.level}`">
                {{ issueText(issue) }}
              </li>
            </ul>
            <span v-else class="muted">Nada a corrigir</span>
          </td>
        </tr>
      </tbody>
    </AppTable>
  </AppCard>
</template>

<style scoped>
.columns {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-4);
  font-size: var(--text-sm);
}

.columns__label {
  margin-right: var(--space-2);
  color: var(--color-text-soft);
}

.chip {
  padding: 0.15rem 0.6rem;
  border-radius: var(--radius-pill);
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
  font-size: var(--text-xs);
  font-weight: 500;
}

.chip__arrow {
  opacity: 0.7;
}

.notes {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0 0 var(--space-4);
  padding: var(--space-3) var(--space-4);
  list-style: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
}

.notes li {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  overflow-wrap: anywhere;
}

.notes--error {
  background: var(--color-error-bg);
  color: var(--color-error);
}

.notes--warning {
  background: var(--color-warning-bg);
  color: var(--color-warning);
}

.issues {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 18rem; /* um caminho longo não pode espremer a coluna até cada linha virar uma torre de letras */
  margin: 0;
  padding: 0;
  list-style: none;
  overflow-wrap: break-word;
  word-break: break-word;
}

.issue--erro {
  color: var(--color-error);
}

.issue--aviso {
  color: var(--color-warning);
}

.muted {
  color: var(--color-text-muted);
}

.cell-name {
  max-width: 14rem;
  font-weight: 600;
  overflow-wrap: anywhere; /* um título de uma palavra só e enorme não alarga a tabela */
}

.row--bad {
  background: var(--color-error-bg);
}
</style>

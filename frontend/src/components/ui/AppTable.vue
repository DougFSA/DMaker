<script setup lang="ts">
/* Casca de tabela: rolagem horizontal só dentro do card (a página nunca rola de lado) e cabeçalho
   fixo. O conteúdo (thead/tbody) vem do slot, para cada tela montar suas colunas. */
defineProps<{ caption: string }>()
</script>

<template>
  <div class="table-wrap" tabindex="0" role="region" :aria-label="caption">
    <table class="table">
      <caption class="visually-hidden">
        {{
          caption
        }}
      </caption>
      <slot />
    </table>
  </div>
</template>

<style scoped>
.table-wrap {
  width: 100%;
  overflow-x: auto;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.table :deep(th) {
  padding: var(--space-3) var(--space-4);
  text-align: left;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
  border-bottom: 1px solid var(--color-border);
  white-space: nowrap;
}

.table :deep(td) {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  vertical-align: middle;
}

.table :deep(tbody tr:last-child td) {
  border-bottom: 0;
}

.table :deep(tbody tr.is-clickable) {
  cursor: pointer;
  transition: background var(--transition);
}

.table :deep(tbody tr.is-clickable:hover) {
  background: var(--color-surface-hover);
}

.table :deep(.cell-num) {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>

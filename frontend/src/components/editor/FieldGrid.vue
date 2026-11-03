<script setup lang="ts">
/* Uma grade de campos da spec: percorre uma lista de `FieldDef` (lib/editorFields) e desenha um SpecField de cada.
   O slot recebe campos avulsos, para misturar os da lista com os que têm opções ou regras próprias. */
import type { FieldDef } from '@/lib/editorFields'
import SpecField from './SpecField.vue'

withDefaults(
  defineProps<{
    fields?: FieldDef[]
    /** Caminho do item na spec ("timeline.2", "audio"). */
    base?: string
  }>(),
  { fields: () => [], base: '' },
)
</script>

<template>
  <div class="field-grid">
    <SpecField v-for="field in fields" :key="field.key" :field="field" :base="base" />
    <slot />
  </div>
</template>

<style scoped>
.field-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
  gap: var(--space-3) var(--space-4);
  align-items: start;
}
</style>

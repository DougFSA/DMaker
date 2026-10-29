<script setup lang="ts">
/* Um grupo do painel Filtros (Reenquadrar, Cor, Fade...): o nome, o "×" que devolve o grupo ao padrão e os campos
   do catálogo. O texto e o número esperam 300 ms de silêncio antes de gravar; lista e caixa gravam na hora. */
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import type { FieldDef } from '@/lib/editorFields'
import { transitionItems, type OptionItem } from '@/lib/editorLabels'
import type { FilterGroup } from '@/lib/filterCatalog'
import { useEditorStore } from '@/stores/editor'
import SpecField from './SpecField.vue'

/** A espera dos campos de texto e número: cada tecla reinicia, e a spec só muda quando a pessoa para. */
const FILTER_DEBOUNCE_MS = 300

defineProps<{
  group: FilterGroup
  /** Onde o item mora na spec ("timeline.2", "output"); o campo é `${base}.${field.key}`. */
  base: string
  /** Os formatos de saída, para o campo que lista os presets do servidor. */
  presets: OptionItem[]
  /** Falso nos grupos que o item não vale sem (o texto da legenda, o arquivo da música). */
  removable: boolean
}>()

defineEmits<{ remove: [] }>()

const editor = useEditorStore()

/** As listas que o servidor mantém fora do schema: as transições do catálogo e os formatos. */
function choicesOf(field: FieldDef, presets: OptionItem[]): OptionItem[] | undefined {
  if (field.choicesFrom === 'transitions') return transitionItems(editor.transitions)
  if (field.choicesFrom === 'presets') return presets
  return undefined
}
</script>

<template>
  <section class="group" :data-group-id="group.id" :aria-label="group.label">
    <header class="group__head">
      <h4 class="group__title">{{ group.label }}</h4>
      <AppButton
        v-if="removable"
        size="sm"
        variant="ghost"
        icon-only
        :aria-label="`Remover ${group.label}`"
        title="Remover este filtro e voltar ao padrão"
        @click="$emit('remove')"
      >
        <AppIcon name="x" :size="16" />
      </AppButton>
    </header>
    <div class="group__fields">
      <SpecField
        v-for="field in group.fields"
        :key="field.key"
        :field="field"
        :base="base"
        :choices="choicesOf(field, presets)"
        :debounce-ms="FILTER_DEBOUNCE_MS"
      />
    </div>
  </section>
</template>

<style scoped>
.group {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.group__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.group__title {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.group__fields {
  display: grid;
  /* o painel é estreito: duas colunas quando cabem, uma quando não */
  grid-template-columns: repeat(auto-fill, minmax(6.25rem, 1fr));
  gap: var(--space-3);
  align-items: start;
}
</style>

<script setup lang="ts">
/* A moldura de um cartão da lista de trechos ou de sobreposições: número, resumo, tipo e as ações de subir,
   descer, duplicar e remover. O formulário do item entra pelo slot e só é desenhado com o cartão aberto. */
import { computed } from 'vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppSelect from '@/components/ui/AppSelect.vue'

export interface TypeOption {
  value: string
  label: string
}

const props = defineProps<{
  /** Posição do item na lista, a partir de 1. */
  position: number
  /** O que a lista é, no singular, para os nomes acessíveis ("trecho", "sobreposição"). */
  noun: string
  /** O gênero do substantivo, para "o trecho" e "a sobreposição". */
  feminine?: boolean
  summary: string
  type: string
  typeOptions: TypeOption[]
  canMoveUp: boolean
  canMoveDown: boolean
}>()

defineEmits<{
  'change-type': [type: string]
  up: []
  down: []
  duplicate: []
  remove: []
}>()

const expanded = defineModel<boolean>('expanded', { default: false })

/** "o trecho 2" / "a sobreposição 2", e as contrações "do" / "da". */
const article = computed(() => (props.feminine ? 'a' : 'o'))
const named = computed(() => `${props.noun} ${props.position}`)
</script>

<template>
  <article class="card" :data-expanded="expanded">
    <header class="card__head">
      <button type="button" class="card__toggle" :aria-expanded="expanded" @click="expanded = !expanded">
        <AppIcon :name="expanded ? 'chevron-down' : 'chevron-right'" :size="16" />
        <AppBadge>{{ position }}</AppBadge>
        <span class="card__summary">{{ summary || 'sem conteúdo ainda' }}</span>
      </button>
      <AppSelect
        class="card__type"
        :label="`Tipo d${article} ${named}`"
        hide-label
        :model-value="type"
        :options="typeOptions"
        @update:model-value="$emit('change-type', $event)"
      />
      <div class="card__actions">
        <AppButton variant="ghost" size="sm" icon-only :disabled="!canMoveUp" :aria-label="`Subir ${article} ${named}`" @click="$emit('up')">
          <AppIcon name="chevron-down" :size="16" class="card__flip" />
        </AppButton>
        <AppButton variant="ghost" size="sm" icon-only :disabled="!canMoveDown" :aria-label="`Descer ${article} ${named}`" @click="$emit('down')">
          <AppIcon name="chevron-down" :size="16" />
        </AppButton>
        <AppButton variant="ghost" size="sm" icon-only :aria-label="`Duplicar ${article} ${named}`" @click="$emit('duplicate')">
          <AppIcon name="copy" :size="16" />
        </AppButton>
        <AppButton variant="ghost" size="sm" icon-only :aria-label="`Remover ${article} ${named}`" @click="$emit('remove')">
          <AppIcon name="x" :size="16" />
        </AppButton>
      </div>
    </header>
    <div v-if="expanded" class="card__body"><slot /></div>
  </article>
</template>

<style scoped>
.card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.card__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
}

.card__toggle {
  display: inline-flex;
  flex: 1;
  align-items: center;
  gap: var(--space-2);
  min-width: 8rem;
  padding: var(--space-1) 0;
  border: 0;
  background: transparent;
  text-align: left;
  color: var(--color-text);
}

.card__summary {
  overflow: hidden;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card__type {
  width: 11rem;
}

.card__actions {
  display: flex;
  gap: var(--space-1);
}

.card__flip {
  transform: rotate(180deg);
}

.card__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4) var(--space-4);
  border-top: 1px solid var(--color-border);
}
</style>

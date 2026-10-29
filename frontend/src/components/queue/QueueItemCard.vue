<script setup lang="ts">
/* Um item da fila: o título e o estado, o andamento (capítulo, fala e quanto falta), os botões que o estado
   permite e, quando há, os arquivos prontos. Não fala com o servidor: quem comanda é a tela, pelo evento `act`. */
import { computed } from 'vue'
import type { QueueItem } from '@/api'
import QueueFiles from '@/components/queue/QueueFiles.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import {
  ACTION_HINTS,
  ACTION_LABELS,
  actionsFor,
  DANGEROUS_ACTIONS,
  describeProgress,
  hasErrorDetails,
  itemMeta,
  showsProgress,
  stateTone,
  type MoveLimits,
  type QueueAction,
} from '@/lib/queue'

const props = defineProps<{
  item: QueueItem
  /** Um comando para este item está esperando a resposta do servidor. */
  working?: boolean
  /** Para onde o item ainda pode andar na fila; ausente quando ele não espera a vez. */
  limits?: MoveLimits
}>()

defineEmits<{ act: [action: QueueAction] }>()

const actions = computed(() => actionsFor(props.item.state))
const meta = computed(() => itemMeta(props.item).join(' · '))
const progress = computed(() => describeProgress(props.item))
/** Rodando e ainda sem fala pronta: não há porcentagem para mostrar, então a barra fica indeterminada. */
const percent = computed(() => (props.item.state === 'running' && props.item.percent === 0 ? null : props.item.percent))

function blocked(action: QueueAction): boolean {
  if (props.working) return true
  if (action === 'up') return !props.limits?.up
  if (action === 'down') return !props.limits?.down
  return false
}
</script>

<template>
  <li class="item" :data-queue-id="item.id" :data-state="item.state">
    <div class="item__head">
      <h3 class="item__title">{{ item.title }}</h3>
      <AppBadge :tone="stateTone(item.state)" dot>{{ item.state_label }}</AppBadge>
    </div>
    <p class="item__meta">{{ meta }}</p>

    <ProgressBar v-if="showsProgress(item.state)" :value="percent" :label="`Andamento de ${item.title}`" />
    <p class="item__progress">{{ progress }}</p>
    <p v-if="item.state === 'running' && item.chapter_title" class="item__meta">{{ item.chapter_title }}</p>
    <p v-if="item.note" class="item__meta">{{ item.note }}</p>
    <details v-if="item.state === 'failed' && hasErrorDetails(item.error)" class="item__error">
      <summary>Ver o erro completo</summary>
      <pre>{{ item.error }}</pre>
    </details>
    <p v-if="item.state === 'done'" class="item__meta">Pasta: {{ item.output_dir }}</p>

    <div v-if="actions.length" class="item__actions">
      <AppButton
        v-for="action in actions"
        :key="action"
        size="sm"
        :variant="DANGEROUS_ACTIONS.has(action) ? 'danger' : 'secondary'"
        :disabled="blocked(action)"
        :title="ACTION_HINTS[action]"
        :aria-label="`${ACTION_LABELS[action]}: ${item.title}`"
        :data-action="action"
        @click="$emit('act', action)"
      >
        {{ ACTION_LABELS[action] }}
      </AppButton>
    </div>

    <QueueFiles :files="item.files" />
  </li>
</template>

<style scoped>
.item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.item[data-state='running'] {
  border-color: var(--color-accent-soft);
}

.item__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-3);
}

.item__title {
  min-width: 0;
  font-size: var(--text-md);
  font-weight: 600;
  overflow-wrap: anywhere;
}

.item__meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow-wrap: anywhere;
}

.item__progress {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.item[data-state='failed'] .item__progress {
  color: var(--color-error);
}

.item__error summary {
  width: fit-content;
  font-size: var(--text-xs);
  color: var(--color-text-soft);
  cursor: pointer;
}

.item__error pre {
  max-height: 12rem;
  margin: var(--space-2) 0 0;
  padding: var(--space-3);
  overflow: auto;
  border-radius: var(--radius-sm);
  background: var(--color-bg-soft);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  white-space: pre-wrap;
}

.item__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-1);
}
</style>

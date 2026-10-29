<script setup lang="ts">
/* Confirmação de uma ação que não se desfaz (apagar voz, modelo ou projeto), no lugar do `window.confirm`.
   É um AlertDialog do Reka UI: anuncia-se como alerta, o foco começa em Cancelar e clicar fora não confirma.
   Emite exatamente um de `confirm` ou `cancel` a cada abertura. */
import {
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogRoot,
  AlertDialogTitle,
} from 'reka-ui'
import { watch } from 'vue'
import AppButton from './AppButton.vue'
import AppIcon from './AppIcon.vue'
import './dialog.css'

withDefaults(
  defineProps<{
    title: string
    description?: string
    /** Aviso em destaque, como o que o servidor monta ao apagar um modelo ("Vai apagar X e liberar 2 GB..."). */
    warning?: string
    confirmLabel?: string
    cancelLabel?: string
    /** `danger` pinta o botão de confirmar como destrutivo. */
    tone?: 'default' | 'danger'
    loading?: boolean
  }>(),
  { confirmLabel: 'Confirmar', cancelLabel: 'Cancelar', tone: 'default' },
)

const emit = defineEmits<{ confirm: []; cancel: [] }>()
const open = defineModel<boolean>('open', { default: false })

// Reka fecha o diálogo ao clicar em Confirmar, o que também dispara "fechou" (antes ou depois do nosso clique,
// conforme a ordem dos ouvintes): só um desfecho conta, e o "fechou" espera o clique terminar para saber qual foi
let settled = false

watch(
  open,
  (isOpen) => {
    if (isOpen) settled = false
  },
  { immediate: true },
)

function onConfirm(): void {
  settled = true
  emit('confirm')
}

function onOpenChange(next: boolean): void {
  if (!next) {
    queueMicrotask(() => {
      if (settled) return
      settled = true
      emit('cancel')
    })
  }
  open.value = next
}
</script>

<template>
  <AlertDialogRoot :open="open" @update:open="onOpenChange">
    <AlertDialogPortal>
      <AlertDialogOverlay class="dialog-overlay" />
      <AlertDialogContent class="dialog dialog--sm">
        <header class="dialog__header">
          <div class="dialog__heading">
            <AlertDialogTitle class="dialog__title">{{ title }}</AlertDialogTitle>
          </div>
        </header>
        <AlertDialogDescription as="div" class="dialog__body confirm__body">
          <p v-if="description" class="confirm__text">{{ description }}</p>
          <p v-if="warning" :class="['confirm__warning', `confirm__warning--${tone}`]">
            <AppIcon name="alert" :size="18" />
            <span>{{ warning }}</span>
          </p>
          <slot />
        </AlertDialogDescription>
        <footer class="dialog__footer">
          <AlertDialogCancel as-child>
            <AppButton>{{ cancelLabel }}</AppButton>
          </AlertDialogCancel>
          <AlertDialogAction as-child>
            <AppButton :variant="tone === 'danger' ? 'danger' : 'primary'" :loading="loading" @click="onConfirm">
              {{ confirmLabel }}
            </AppButton>
          </AlertDialogAction>
        </footer>
      </AlertDialogContent>
    </AlertDialogPortal>
  </AlertDialogRoot>
</template>

<style>
/* sem scoped: como o resto do diálogo, o conteúdo vive no fim do body */
.confirm__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.confirm__text {
  font-size: var(--text-md);
  color: var(--color-text-soft);
}

.confirm__warning {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}

.confirm__warning svg {
  flex-shrink: 0;
  margin-top: 0.1rem;
}

.confirm__warning--default {
  background: var(--color-warning-bg);
  color: var(--color-warning);
}

.confirm__warning--danger {
  background: var(--color-error-bg);
  color: var(--color-error);
}
</style>

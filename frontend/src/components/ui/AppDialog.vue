<script setup lang="ts">
/* Diálogo acessível (foco preso, Esc fecha, leitor de tela anuncia o título) sobre o Dialog do Reka UI. */
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import AppIcon from './AppIcon.vue'

withDefaults(
  defineProps<{
    title: string
    description?: string
    size?: 'sm' | 'md' | 'lg' | 'xl'
  }>(),
  { size: 'md' },
)

const open = defineModel<boolean>('open', { default: false })
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="dialog-overlay" />
      <DialogContent :class="['dialog', `dialog--${size}`]">
        <header class="dialog__header">
          <div class="dialog__heading">
            <DialogTitle class="dialog__title">{{ title }}</DialogTitle>
            <DialogDescription v-if="description" class="dialog__description">
              {{ description }}
            </DialogDescription>
          </div>
          <DialogClose class="dialog__close" aria-label="Fechar">
            <AppIcon name="x" :size="18" />
          </DialogClose>
        </header>
        <div class="dialog__body"><slot /></div>
        <footer v-if="$slots.footer" class="dialog__footer"><slot name="footer" /></footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style>
/* sem scoped: o conteúdo é teletransportado para o fim do body */
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: var(--color-overlay);
  backdrop-filter: blur(3px);
  animation: dialog-fade 160ms ease;
}

.dialog {
  position: fixed;
  top: 50%;
  left: 50%;
  z-index: 61;
  display: flex;
  flex-direction: column;
  width: min(calc(100vw - 2rem), 34rem);
  max-height: calc(100vh - 2rem);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  transform: translate(-50%, -50%);
  animation: dialog-in 180ms ease;
}

.dialog--sm {
  width: min(calc(100vw - 2rem), 26rem);
}

.dialog--lg {
  width: min(calc(100vw - 2rem), 46rem);
}

.dialog--xl {
  width: min(calc(100vw - 2rem), 64rem);
}

.dialog:focus {
  outline: none;
}

.dialog__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-5) var(--space-3);
}

.dialog__title {
  font-size: var(--text-lg);
  font-weight: 600;
}

.dialog__description {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.dialog__close {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 2rem;
  height: 2rem;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-soft);
  transition: background var(--transition);
}

.dialog__close:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.dialog__body {
  flex: 1;
  min-height: 0;
  padding: var(--space-3) var(--space-5) var(--space-5);
  overflow-y: auto;
}

.dialog__footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-border);
}

@keyframes dialog-fade {
  from {
    opacity: 0;
  }
}

@keyframes dialog-in {
  from {
    opacity: 0;
    transform: translate(-50%, -48%) scale(0.98);
  }
}
</style>

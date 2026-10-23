<script setup lang="ts">
import { useToastsStore } from '@/stores/toasts'
import AppIcon from './AppIcon.vue'

const toasts = useToastsStore()

function runAction(id: number, run: () => void): void {
  run()
  toasts.dismiss(id)
}
</script>

<template>
  <div class="toast-host" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts.items"
        :key="toast.id"
        :class="['toast', `toast--${toast.tone}`]"
        :role="toast.tone === 'error' ? 'alert' : 'status'"
      >
        <AppIcon :name="toast.tone === 'success' ? 'check' : toast.tone === 'error' ? 'alert' : 'info'" />
        <div class="toast__text">
          <strong class="toast__title">{{ toast.title }}</strong>
          <p v-if="toast.description" class="toast__description">{{ toast.description }}</p>
          <button
            v-if="toast.action"
            type="button"
            class="toast__action"
            @click="runAction(toast.id, toast.action.run)"
          >
            {{ toast.action.label }}
          </button>
        </div>
        <button type="button" class="toast__close" aria-label="Dispensar aviso" @click="toasts.dismiss(toast.id)">
          <AppIcon name="x" :size="16" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  right: var(--space-5);
  bottom: var(--space-5);
  z-index: 80;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  width: min(24rem, calc(100vw - 2rem));
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-left-width: 4px;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  pointer-events: auto;
}

.toast--success {
  border-left-color: var(--color-success);
  color: var(--color-text);
}

.toast--success > svg {
  color: var(--color-success);
}

.toast--error {
  border-left-color: var(--color-error);
}

.toast--error > svg {
  color: var(--color-error);
}

.toast--info {
  border-left-color: var(--color-info);
}

.toast--info > svg {
  color: var(--color-info);
}

.toast > svg {
  flex-shrink: 0;
  margin-top: 0.1rem;
}

.toast__text {
  flex: 1;
  min-width: 0;
}

.toast__title {
  display: block;
  font-size: var(--text-sm);
  font-weight: 600;
}

.toast__description {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  overflow-wrap: anywhere;
  white-space: pre-line;
}

.toast__action {
  margin-top: var(--space-2);
  padding: 0;
  border: 0;
  background: none;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-accent-text);
}

.toast__action:hover {
  text-decoration: underline;
}

.toast__close {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 1.5rem;
  height: 1.5rem;
  border: 0;
  border-radius: 50%;
  background: none;
  color: var(--color-text-muted);
}

.toast__close:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.toast-enter-active,
.toast-leave-active {
  transition:
    opacity 200ms ease,
    transform 200ms ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(1rem);
}
</style>

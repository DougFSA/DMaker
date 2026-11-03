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
import './dialog.css'

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

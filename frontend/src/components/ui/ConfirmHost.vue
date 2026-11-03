<script setup lang="ts">
/* Desenha a confirmação da vez (a fila de `useConfirm`). Fica uma vez só, no App, ao lado do ToastHost. */
import { useConfirmStore } from '@/stores/confirm'
import ConfirmDialog from './ConfirmDialog.vue'

const confirm = useConfirmStore()
</script>

<template>
  <ConfirmDialog
    v-if="confirm.current"
    :key="confirm.current.id"
    :open="true"
    v-bind="confirm.current.options"
    @confirm="confirm.answer(true)"
    @cancel="confirm.answer(false)"
  />
</template>

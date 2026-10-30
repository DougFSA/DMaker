<script setup lang="ts">
/* O que fica acima da caixa de mensagem quando há anexos: as fichas dos arquivos, os avisos de antes de enviar (imagem
   para um modelo que não lê imagem, vídeo numa Conversa livre) e o que a tela recusou ao escolher os arquivos. */
import AppButton from '@/components/ui/AppButton.vue'
import type { AttachmentCard, AttachmentWarning } from '@/lib/agentAttachments'
import AgentAttachmentCard from './AgentAttachmentCard.vue'

defineProps<{
  cards: AttachmentCard[]
  warnings: AttachmentWarning[]
  /** O que a tela recusou ao escolher os arquivos; vazio quando nada. */
  notice: string
  conversationId: string | null
}>()
const emit = defineEmits<{ remove: [card: AttachmentCard]; 'use-model': [name: string] }>()
</script>

<template>
  <div class="tray">
    <ul v-if="cards.length" class="tray__files" aria-label="Arquivos anexados">
      <AgentAttachmentCard v-for="card in cards" :key="card.key" :card="card" :conversation-id="conversationId" removable @remove="emit('remove', card)" />
    </ul>
    <div v-for="warning in warnings" :key="warning.code" class="tray__note" data-tone="error" :data-code="warning.code" role="alert">
      <p>{{ warning.text }}</p>
      <span v-if="warning.models.length" class="tray__actions">
        <AppButton v-for="name in warning.models" :key="name" size="sm" variant="secondary" @click="emit('use-model', name)">Usar {{ name }}</AppButton>
      </span>
    </div>
    <p v-if="notice" class="tray__note" data-tone="warning" data-code="notice" role="status">{{ notice }}</p>
  </div>
</template>

<style scoped>
.tray {
  display: grid;
  flex: 1 1 100%;
  gap: var(--space-2);
  min-width: 0;
}

.tray__files {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.tray__note {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.tray__note[data-tone='warning'] {
  background: var(--color-warning-bg);
  color: var(--color-warning);
}

.tray__note[data-tone='error'] {
  background: var(--color-error-bg);
  color: var(--color-error);
}

.tray__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
</style>

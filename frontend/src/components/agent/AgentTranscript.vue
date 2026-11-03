<script setup lang="ts">
/* A conversa desenhada: a mesma lista de itens serve ao turno ao vivo e à transcrição salva pelo servidor. */
import type { AgentKit } from '@/api'
import { kitTitle, type ChatItem } from '@/lib/agent'
import AppBadge from '@/components/ui/AppBadge.vue'
import AgentAttachmentCard from './AgentAttachmentCard.vue'
import AgentConfirmation from './AgentConfirmation.vue'
import AgentNotice from './AgentNotice.vue'
import AgentThinking from './AgentThinking.vue'
import AgentToolStep from './AgentToolStep.vue'

defineProps<{
  items: ChatItem[]
  kits: AgentKit[]
  /** A conversa desenhada: é por ela que a miniatura de uma imagem enviada se busca. */
  conversationId?: string | null
}>()
const emit = defineEmits<{ answer: [confirmationId: string, approve: boolean] }>()
</script>

<template>
  <template v-for="item in items" :key="item.id">
    <div v-if="item.kind === 'user'" class="sent">
      <ul v-if="item.attachments?.length" class="sent__files" aria-label="Arquivos enviados com a mensagem">
        <AgentAttachmentCard v-for="card in item.attachments" :key="card.key" :card="card" :conversation-id="conversationId ?? null" />
      </ul>
      <p class="bubble bubble--user">{{ item.text }}</p>
    </div>
    <p v-else-if="item.kind === 'kits'" class="kits">
      Kit: {{ item.kits.map((name) => kitTitle(name, kits)).join(' e ') }}
    </p>
    <AgentThinking v-else-if="item.kind === 'thinking'" :item="item" />
    <AgentToolStep v-else-if="item.kind === 'tool'" :tool="item" />
    <AgentConfirmation
      v-else-if="item.kind === 'confirmation'"
      :confirmation="item"
      @answer="(id, approve) => emit('answer', id, approve)"
    />
    <div v-else-if="item.kind === 'answer'" class="bubble bubble--agent" :data-streaming="item.streaming">
      {{ item.text }}
      <AppBadge v-if="item.interrupted" tone="warning" class="bubble__mark">interrompida</AppBadge>
    </div>
    <AgentNotice v-else-if="item.kind === 'notice'" :notice="item" />
    <p v-else-if="item.kind === 'error'" class="bubble bubble--error" role="alert">{{ item.text }}</p>
  </template>
</template>

<style scoped>
.bubble {
  max-width: min(46rem, 100%);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* a mensagem da pessoa: os arquivos que seguiram com ela ficam logo acima do texto, do mesmo lado */
.sent {
  display: grid;
  align-self: flex-end;
  gap: var(--space-2);
  justify-items: end;
  max-width: min(46rem, 100%);
}

.sent__files {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.bubble--user {
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}

.bubble--agent {
  align-self: flex-start;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}

/* o cursor piscando mostra que a resposta ainda está chegando */
.bubble--agent[data-streaming='true']::after {
  content: '';
  display: inline-block;
  width: 0.5rem;
  height: 1em;
  margin-left: 0.15rem;
  vertical-align: text-bottom;
  background: var(--color-accent);
  animation: blink 1s steps(2, start) infinite;
}

.bubble__mark {
  margin-left: var(--space-2);
  vertical-align: middle;
}

.bubble--error {
  align-self: flex-start;
  background: var(--color-error-bg);
  color: var(--color-error);
}

.kits {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

@keyframes blink {
  to {
    visibility: hidden;
  }
}
</style>

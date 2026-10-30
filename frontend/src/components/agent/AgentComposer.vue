<script setup lang="ts">
/* A caixa de mensagem do agente. Enquanto ele responde, o botão vira Parar. O slot `above` recebe as fichas dos
   anexos e o slot `actions` os botões ao lado do envio (anexar um arquivo); ficam vazios até haver anexos. */
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'

defineProps<{
  placeholder: string
  /** O agente está respondendo: o botão Enviar vira Parar. */
  busy: boolean
  /** A pessoa já clicou em Parar e o servidor ainda não terminou. */
  stopping: boolean
  /** Pode enviar: o modelo local está no ar e o modelo escolhido está instalado e serve ao modo da conversa. */
  ready: boolean
}>()

const emit = defineEmits<{ submit: []; stop: [] }>()
const message = defineModel<string>({ required: true })
</script>

<template>
  <form class="composer" @submit.prevent="emit('submit')">
    <div v-if="$slots.above" class="composer__above"><slot name="above" /></div>
    <label class="sr-only" for="agent-message">Mensagem para o agente</label>
    <textarea
      id="agent-message"
      v-model="message"
      rows="2"
      :placeholder="placeholder"
      @keydown.enter.exact.prevent="emit('submit')"
    />
    <div class="composer__row">
      <div class="composer__actions"><slot name="actions" /></div>
      <AppButton v-if="busy" variant="secondary" :disabled="stopping" @click="emit('stop')">
        <AppIcon name="stop" :size="16" />
        {{ stopping ? 'Parando...' : 'Parar' }}
      </AppButton>
      <AppButton v-else type="submit" variant="primary" :disabled="!message.trim() || !ready">Enviar</AppButton>
    </div>
  </form>
</template>

<style scoped>
.composer {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}

.composer:focus-within {
  border-color: var(--color-focus);
}

.composer textarea {
  width: 100%;
  min-width: 0;
  padding: var(--space-1);
  border: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
  resize: vertical;
}

.composer textarea:focus {
  outline: none;
}

.composer__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.composer__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.composer__above {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>

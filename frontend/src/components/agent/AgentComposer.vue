<script setup lang="ts">
/* A caixa de mensagem do agente. Enquanto ele responde, o botão vira Parar. O slot `above` recebe as fichas dos
   anexos e o slot `actions` os botões ao lado do envio (anexar um arquivo). Arrastar arquivos para a caixa e colar uma
   imagem (um print, por exemplo) também anexam: a caixa só avisa quais arquivos chegaram, quem usa decide o que fazer. */
import { ref } from 'vue'
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
  /** Há arquivos anexados: a mensagem pode seguir só com eles, sem texto. */
  hasAttachments?: boolean
}>()

const emit = defineEmits<{ submit: []; stop: []; attach: [files: File[]] }>()
const message = defineModel<string>({ required: true })
const dropping = ref(false)

function carriesFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files')
}

function onDragOver(event: DragEvent): void {
  if (!carriesFiles(event)) return
  event.preventDefault()
  dropping.value = true
}

function onDragLeave(event: DragEvent): void {
  const form = event.currentTarget as HTMLElement
  // passar sobre um filho da caixa dispara o `dragleave` da caixa: só conta quando o ponteiro sai de verdade
  if (!form.contains(event.relatedTarget as Node | null)) dropping.value = false
}

function onDrop(event: DragEvent): void {
  dropping.value = false
  const files = Array.from(event.dataTransfer?.files ?? [])
  // o botão Anexar também recebe arquivos soltos nele (e já cuidou deles, o que marca o evento): não anexa duas vezes
  if (!files.length || event.defaultPrevented) return
  event.preventDefault()
  emit('attach', files)
}

function onPaste(event: ClipboardEvent): void {
  const files = Array.from(event.clipboardData?.files ?? [])
  if (!files.length) return // texto colado segue como texto
  event.preventDefault()
  emit('attach', files)
}
</script>

<template>
  <form
    class="composer"
    :class="{ 'composer--dropping': dropping }"
    @submit.prevent="emit('submit')"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <div v-if="$slots.above" class="composer__above"><slot name="above" /></div>
    <label class="sr-only" for="agent-message">Mensagem para o agente</label>
    <textarea
      id="agent-message"
      v-model="message"
      rows="2"
      :placeholder="placeholder"
      @keydown.enter.exact.prevent="emit('submit')"
      @paste="onPaste"
    />
    <div class="composer__row">
      <div class="composer__actions"><slot name="actions" /></div>
      <AppButton v-if="busy" variant="secondary" :disabled="stopping" @click="emit('stop')">
        <AppIcon name="stop" :size="16" />
        {{ stopping ? 'Parando...' : 'Parar' }}
      </AppButton>
      <AppButton v-else type="submit" variant="primary" :disabled="!(message.trim() || hasAttachments) || !ready">Enviar</AppButton>
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

/* arrastando arquivos sobre a caixa: ela acende, para a pessoa saber que pode soltar */
.composer--dropping {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
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

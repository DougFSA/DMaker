<script setup lang="ts">
/* As conversas salvas, a mais recente primeiro: abrir, renomear e apagar. O apagar só avisa (`remove`): quem pergunta
   "tem certeza?" é a tela, com o diálogo de confirmação. */
import { nextTick, ref } from 'vue'
import type { AgentConversationSummary } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { formatRelative } from '@/lib/format'
import { MODE_LABELS } from '@/lib/agentModels'

defineProps<{
  conversations: AgentConversationSummary[]
  /** A conversa aberta; nula na conversa nova, que ainda não está salva. */
  activeId: string | null
}>()

const emit = defineEmits<{
  select: [id: string]
  rename: [id: string, title: string]
  remove: [id: string]
}>()

const editingId = ref<string | null>(null)
const editedTitle = ref('')
const input = ref<HTMLInputElement[] | HTMLInputElement | null>(null)

async function startRename(conversation: AgentConversationSummary): Promise<void> {
  editingId.value = conversation.id
  editedTitle.value = conversation.title
  await nextTick()
  const field = Array.isArray(input.value) ? input.value[0] : input.value
  field?.focus()
  field?.select()
}

function commitRename(conversation: AgentConversationSummary): void {
  if (editingId.value !== conversation.id) return
  const title = editedTitle.value.trim()
  editingId.value = null
  if (title && title !== conversation.title) emit('rename', conversation.id, title)
}

function cancelRename(): void {
  editingId.value = null
}

function when(conversation: AgentConversationSummary): string {
  return formatRelative(Date.parse(conversation.updated_at) / 1000)
}
</script>

<template>
  <div class="conversations">
    <h2 class="conversations__title">Conversas</h2>
    <p v-if="!conversations.length" class="conversations__empty">
      Nenhuma conversa salva ainda. A primeira aparece aqui quando você enviar uma mensagem.
    </p>
    <ul v-else class="conversations__list">
      <li
        v-for="conversation in conversations"
        :key="conversation.id"
        class="row"
        :class="{ 'row--active': conversation.id === activeId }"
        :data-conversation="conversation.id"
      >
        <form v-if="editingId === conversation.id" class="row__rename" @submit.prevent="commitRename(conversation)">
          <label class="sr-only" :for="`rename-${conversation.id}`">Novo nome da conversa</label>
          <input
            :id="`rename-${conversation.id}`"
            ref="input"
            v-model="editedTitle"
            class="row__input"
            maxlength="120"
            autocomplete="off"
            @keydown.esc.prevent="cancelRename"
            @blur="cancelRename"
          />
        </form>
        <template v-else>
          <button
            type="button"
            class="row__open"
            :aria-current="conversation.id === activeId ? 'true' : undefined"
            @click="emit('select', conversation.id)"
          >
            <span class="row__name">{{ conversation.title }}</span>
            <span class="row__meta">
              <span v-if="conversation.running" class="row__running">respondendo</span>
              <span v-else>{{ when(conversation) }}</span>
              <span>{{ conversation.model }}</span>
              <span v-if="conversation.mode === 'free'">{{ MODE_LABELS.free }}</span>
            </span>
          </button>
          <div class="row__actions">
            <AppButton
              variant="ghost"
              size="sm"
              icon-only
              :aria-label="`Renomear a conversa ${conversation.title}`"
              @click="startRename(conversation)"
            >
              <AppIcon name="edit" :size="16" />
            </AppButton>
            <AppButton
              variant="ghost"
              size="sm"
              icon-only
              :aria-label="`Apagar a conversa ${conversation.title}`"
              @click="emit('remove', conversation.id)"
            >
              <AppIcon name="trash" :size="16" />
            </AppButton>
          </div>
        </template>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.conversations {
  display: grid;
  gap: var(--space-2);
  align-content: start;
}

.conversations__title {
  padding: 0 var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.conversations__empty {
  padding: var(--space-2);
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}

.conversations__list {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.row {
  position: relative;
  display: flex;
  align-items: stretch;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
}

.row:hover,
.row:focus-within {
  background: var(--color-surface-hover);
}

.row--active {
  border-color: var(--color-border-strong);
  background: var(--color-accent-bg);
}

.row__open {
  display: grid;
  flex: 1;
  gap: 0.15rem;
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text);
  text-align: left;
  cursor: pointer;
}

.row__open:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: -2px;
}

.row__name {
  overflow: hidden;
  font-size: var(--text-md);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0 var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.row__running {
  color: var(--color-accent-text);
  font-weight: 600;
}

/* os botões aparecem sobre a linha quando ela é a aberta, está com o mouse ou o foco, e sempre na tela estreita (toque) */
.row__actions {
  display: none;
  flex: none;
  align-items: center;
  padding-right: var(--space-1);
}

.row:hover .row__actions,
.row:focus-within .row__actions,
.row--active .row__actions {
  display: flex;
}

@container agent (max-width: 760px) {
  .row__actions {
    display: flex;
  }
}

.row__rename {
  flex: 1;
  padding: var(--space-1);
}

.row__input {
  width: 100%;
  min-height: 2.25rem;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-focus);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
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

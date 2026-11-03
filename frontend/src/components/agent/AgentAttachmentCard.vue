<script setup lang="ts">
/* A ficha de um arquivo anexado: o tipo, o nome, o tamanho e, no texto que não coube no contexto, quanto foi cortado.
   A imagem mostra a miniatura (servida pela própria conversa, não por /api/file). Serve à caixa de mensagem, onde dá
   para tirar o anexo, e à mensagem já enviada, onde a ficha só informa. */
import { computed, ref, watch } from 'vue'
import { api } from '@/api'
import AppIcon, { type IconName } from '@/components/ui/AppIcon.vue'
import { cardDetail, cutNote, kindLabel, type AttachmentCard } from '@/lib/agentAttachments'

const props = defineProps<{
  card: AttachmentCard
  /** A conversa dona do anexo: é por ela que a miniatura da imagem se busca. */
  conversationId: string | null
  /** Mostra o botão de tirar o anexo (só antes de enviar). */
  removable?: boolean
}>()
const emit = defineEmits<{ remove: [] }>()

/** Se a miniatura não carrega (arquivo apagado), a ficha volta ao ícone em vez de mostrar uma imagem quebrada. */
const thumbnailFailed = ref(false)
watch(() => props.card.id, () => (thumbnailFailed.value = false))

const thumbnail = computed(() =>
  props.conversationId && props.card.kind === 'image' && props.card.id && props.card.state === 'ready' && !thumbnailFailed.value
    ? api.agent.conversations.attachments.imageUrl(props.conversationId, props.card.id)
    : undefined,
)

const ICONS: Record<string, IconName> = { Imagem: 'image', Vídeo: 'film', Áudio: 'mic', Planilha: 'table', Documento: 'file' }
const icon = computed<IconName>(() => ICONS[kindLabel(props.card)] ?? 'file')
const note = computed(() => cutNote(props.card))
const meta = computed(() => (props.card.state === 'uploading' ? 'Enviando...' : cardDetail(props.card)))
</script>

<template>
  <li class="file" :data-state="card.state" :data-kind="card.kind ?? 'unknown'">
    <img v-if="thumbnail" class="file__thumb" :src="thumbnail" :alt="`Miniatura de ${card.name}`" loading="lazy" @error="thumbnailFailed = true" />
    <span v-else class="file__icon" aria-hidden="true"><AppIcon :name="icon" :size="18" /></span>
    <span class="file__text">
      <span class="file__name" :title="card.name">{{ card.name }}</span>
      <span class="file__meta">{{ meta }}</span>
      <span v-if="note" class="file__note">{{ note }}</span>
      <span v-if="card.state === 'error'" class="file__error" role="alert">{{ card.error }}</span>
    </span>
    <button v-if="removable && card.state !== 'uploading'" type="button" class="file__remove" :aria-label="`Remover ${card.name}`" @click="emit('remove')">
      <AppIcon name="x" :size="14" />
    </button>
  </li>
</template>

<style scoped>
.file {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  max-width: min(18rem, 100%);
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
  color: var(--color-text);
  list-style: none;
}

.file[data-state='uploading'] {
  opacity: 0.75;
}

.file[data-state='error'] {
  border-color: var(--color-error);
  background: var(--color-error-bg);
}

.file__thumb,
.file__icon {
  flex: none;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: var(--radius-sm);
}

.file__thumb {
  object-fit: cover;
}

.file__icon {
  display: grid;
  place-items: center;
  background: var(--color-surface);
  color: var(--color-text-soft);
}

.file__text {
  display: grid;
  min-width: 0;
  line-height: 1.3;
}

.file__name {
  overflow: hidden;
  font-size: var(--text-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file__meta {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.file__note {
  color: var(--color-warning);
  font-size: var(--text-xs);
}

.file__error {
  color: var(--color-error);
  font-size: var(--text-xs);
  overflow-wrap: anywhere;
}

.file__remove {
  display: grid;
  flex: none;
  place-items: center;
  width: 1.5rem;
  height: 1.5rem;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-soft);
  cursor: pointer;
}

.file__remove:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}
</style>

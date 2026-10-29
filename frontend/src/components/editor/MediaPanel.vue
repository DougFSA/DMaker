<script setup lang="ts">
/* O painel Mídia: as fontes sincronizadas e os arquivos que o projeto já usa, com miniatura e duração. Cada item se
   arrasta para a linha do tempo (na V1 entra no ponto; em outra trilha vira PiP ou imagem), e os botões acrescentam
   arquivo, texto, cartão, logo ou música. As teclas A (no fim da V1) e V (no cursor) agem sobre o item selecionado.
   O que cada gesto vira em operações mora em `lib/mediaInsert`; o painel só pede. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useMediaActions } from '@/composables/useMediaActions'
import { useShortcutHandler } from '@/composables/useEditorShortcuts'
import { isAbsolutePath } from '@/lib/editorPaths'
import { collectMediaEntries, type MediaEntry, type MediaSpec } from '@/lib/media'
import { kindLabel, mediaDurationLabel } from '@/lib/mediaInsert'
import { MEDIA_DND_MIME } from '@/lib/timeline'
import { useEditorStore } from '@/stores/editor'
import { useKeymapStore } from '@/stores/keymap'
import { useMediaDurationsStore } from '@/stores/mediaDurations'
import { useTimelineStore } from '@/stores/timeline'
import { useToastsStore } from '@/stores/toasts'
import MediaThumb from './MediaThumb.vue'

const editor = useEditorStore()
const timeline = useTimelineStore()
const keymap = useKeymapStore()
const durations = useMediaDurationsStore()
const toasts = useToastsStore()
const actions = useMediaActions()

const entries = computed<MediaEntry[]>(() =>
  editor.spec ? collectMediaEntries(editor.spec as MediaSpec, editor.view) : [],
)

const selectedId = ref<string | null>(null)
const selected = computed(() => entries.value.find((entry) => entry.id === selectedId.value) ?? null)

// o item selecionado que saiu do projeto (o último uso dele foi removido) deixa de estar selecionado
watch(entries, (list) => {
  if (!list.some((entry) => entry.id === selectedId.value)) selectedId.value = null
})

// a duração só se mede de caminho absoluto (o servidor não sabe de pasta de projeto) e de vídeo ou áudio
watch(
  () =>
    entries.value
      .filter((entry) => entry.kind !== 'image' && isAbsolutePath(entry.path))
      .map((entry) => entry.path)
      .join('\n'),
  (joined) => void durations.ensure(joined ? joined.split('\n') : []),
  { immediate: true },
)

function durationOf(entry: MediaEntry): string {
  const seconds = durations.seconds[entry.path]
  return typeof seconds === 'number' && seconds > 0 ? mediaDurationLabel(seconds) : ''
}

/** O `src` que a miniatura resolve: o da spec, quando há (arquivo avulso), ou o caminho da fonte sincronizada. */
function thumbSource(entry: MediaEntry): string {
  return entry.src ?? entry.path
}

function isMissing(entry: MediaEntry): boolean {
  return editor.isMissing(thumbSource(entry))
}

function meta(entry: MediaEntry): string {
  return [kindLabel(entry.kind), durationOf(entry), isMissing(entry) ? 'não encontrado' : ''].filter(Boolean).join(' · ')
}

const canEdit = computed(() => !!editor.view)

/* ---------- arrastar, soltar e as teclas A e V ---------- */

function onDragStart(event: DragEvent, entry: MediaEntry): void {
  if (!event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData(MEDIA_DND_MIME, JSON.stringify(entry))
}

let stopDrop: (() => void) | null = null
onMounted(() => {
  stopDrop = timeline.onMediaDrop((payload, hit) => void actions.drop(payload, hit))
})
onBeforeUnmount(() => stopDrop?.())

const NEEDS_SELECTION = 'Selecione um arquivo no painel de mídia.'

function withSelected(act: (entry: MediaEntry) => unknown): void {
  if (selected.value) act(selected.value)
  else toasts.push({ tone: 'error', title: NEEDS_SELECTION })
}

useShortcutHandler('media_append', () => withSelected((entry) => actions.append(entry)))
useShortcutHandler('media_insert', () => withSelected((entry) => actions.insertAtPlayhead(entry)))

/* ---------- teclado na lista ---------- */

function onItemKeydown(event: KeyboardEvent, entry: MediaEntry): void {
  const item = event.currentTarget as HTMLElement
  if (event.key === 'Enter') {
    event.preventDefault()
    selectedId.value = entry.id
    void actions.append(entry)
  } else if (event.key === ' ') {
    event.preventDefault()
    selectedId.value = entry.id
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const row = item.closest('li')
    const sibling = event.key === 'ArrowDown' ? row?.nextElementSibling : row?.previousElementSibling
    sibling?.querySelector<HTMLElement>('[data-media-id]')?.focus()
  }
}
</script>

<template>
  <AppCard class="media" title="Mídia" flush>
    <EmptyState v-if="!editor.spec" icon="film" title="Sem projeto aberto" description="A mídia aparece quando o projeto abrir." />

    <template v-else>
      <div class="media__tools" role="toolbar" aria-label="Adicionar ao projeto">
        <AppButton
          size="sm"
          :disabled="!canEdit || !actions.canPickFile"
          title="Escolher um arquivo: vídeo e imagem entram no fim da V1, áudio vira a música"
          @click="actions.addFile()"
        >
          + Arquivo
        </AppButton>
        <AppButton size="sm" :disabled="!canEdit" title="Texto novo no cursor" @click="actions.addText()">Texto</AppButton>
        <AppButton size="sm" :disabled="!canEdit" title="Cartão novo no fim da V1" @click="actions.addCard()">Cartão</AppButton>
        <AppButton size="sm" :disabled="!canEdit" title="Logo da marca no cursor" @click="actions.addLogo()">Logo</AppButton>
        <AppButton
          size="sm"
          :disabled="!canEdit || !actions.canPickFile"
          title="Escolher a música do projeto"
          @click="actions.addMusic()"
        >
          Música
        </AppButton>
      </div>

      <ul v-if="entries.length > 0" class="media__list" aria-label="Arquivos do projeto">
        <li v-for="entry in entries" :key="entry.id">
          <!-- botão que marca (aria-pressed) e se arrasta; não é listbox, porque a lista que usa o teclado
               para si calaria as teclas A e V do editor enquanto o foco estiver nela -->
          <div
            class="item"
            :class="{ 'item--selected': entry.id === selectedId, 'item--missing': isMissing(entry) }"
            role="button"
            tabindex="0"
            draggable="true"
            :data-media-id="entry.id"
            :aria-pressed="entry.id === selectedId"
            :title="entry.path"
            @click="selectedId = entry.id"
            @dblclick="actions.append(entry)"
            @dragstart="onDragStart($event, entry)"
            @keydown="onItemKeydown($event, entry)"
          >
            <span class="item__thumb">
              <MediaThumb v-if="entry.kind !== 'audio'" :src="thumbSource(entry)" :kind="entry.kind === 'image' ? 'image' : 'video'" compact />
              <span v-else class="item__audio" aria-hidden="true">♪</span>
            </span>
            <span class="item__info">
              <span class="item__name">{{ entry.label }}</span>
              <span class="item__meta">{{ meta(entry) }}</span>
            </span>
          </div>
        </li>
      </ul>
      <p v-else class="media__empty">Nenhum arquivo ainda. Use “+ Arquivo” ou os botões acima.</p>

      <p class="media__hint">
        Arraste para a linha do tempo, ou use
        <kbd>{{ keymap.labelFor('media_append') }}</kbd> para acrescentar ao fim da V1 e
        <kbd>{{ keymap.labelFor('media_insert') }}</kbd> para inserir no cursor.
      </p>
    </template>
  </AppCard>
</template>

<style scoped>
.media__tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  padding: 0 var(--space-4) var(--space-3);
}

.media__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0;
  padding: 0 var(--space-3);
  list-style: none;
  /* a lista rola dentro do painel: arquivo demais não estica a bancada nem empurra a linha do tempo para baixo */
  max-height: var(--editor-side-panel-height, 34rem);
  overflow-y: auto;
}

.item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: grab;
  user-select: none;
}

.item:hover {
  background: var(--color-surface-hover);
}

.item--selected {
  border-color: var(--color-accent-soft);
  background: var(--color-surface-hover);
}

.item--missing .item__name {
  color: var(--color-error);
}

.item__thumb {
  display: grid;
  flex: none;
  place-items: center;
  width: 4.5rem;
  height: 2.75rem;
  border-radius: var(--radius-sm);
  background: var(--color-bg-soft);
}

.item__audio {
  font-size: var(--text-lg);
  color: var(--color-text-muted);
}

.item__info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.item__name {
  overflow: hidden;
  font-size: var(--text-sm);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item__meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.media__empty,
.media__hint {
  padding: var(--space-3) var(--space-4) var(--space-4);
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}

.media__hint kbd {
  padding: 0 var(--space-1);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
}
</style>

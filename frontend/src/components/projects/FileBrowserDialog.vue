<script setup lang="ts">
/* Navegador de arquivos do servidor (GET /api/browse): escolhe vídeos, imagens ou uma pasta de mídia. */
import { computed, ref, watch } from 'vue'
import { api, errorMessage, type BrowseResponse } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { baseName, formatSizeMb } from '@/lib/format'

export type BrowseMode = 'file' | 'files' | 'dir'

const props = defineProps<{ mode: BrowseMode; title?: string }>()
const emit = defineEmits<{ select: [paths: string[]] }>()
const open = defineModel<boolean>('open', { default: false })

// a pasta onde a pessoa estava na última escolha serve de ponto de partida da próxima
let lastFolder = ''

const listing = ref<BrowseResponse | null>(null)
const selected = ref<string[]>([])
const loading = ref(false)
const failure = ref('')

const heading = computed(
  () =>
    props.title ??
    (props.mode === 'dir' ? 'Escolher pasta' : props.mode === 'files' ? 'Escolher arquivos' : 'Escolher arquivo'),
)
const atRoot = computed(() => !listing.value?.path)

async function go(path: string): Promise<void> {
  loading.value = true
  failure.value = ''
  try {
    listing.value = await api.files.browse(path || undefined)
    lastFolder = listing.value.path
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

watch(open, (isOpen) => {
  if (!isOpen) return
  selected.value = []
  void go(lastFolder)
})

function folderLabel(path: string): string {
  // raiz de unidade ("C:/") não tem último trecho útil
  return /^[A-Za-z]:\/?$/.test(path) ? path : baseName(path)
}

function toggle(path: string): void {
  if (props.mode === 'file') {
    selected.value = [path]
    return
  }
  selected.value = selected.value.includes(path)
    ? selected.value.filter((item) => item !== path)
    : [...selected.value, path]
}

function confirm(): void {
  const paths = props.mode === 'dir' ? (listing.value?.path ? [listing.value.path] : []) : selected.value
  if (paths.length === 0) return
  emit('select', paths)
  open.value = false
}

const canConfirm = computed(() =>
  props.mode === 'dir' ? !!listing.value?.path : selected.value.length > 0,
)
</script>

<template>
  <AppDialog v-model:open="open" :title="heading" size="lg" description="Navegue pelas pastas deste computador.">
    <div class="browser">
      <div class="browser__bar">
        <AppButton
          variant="ghost"
          size="sm"
          :disabled="atRoot || loading"
          @click="go(listing?.parent ?? '')"
        >
          <AppIcon name="arrow-left" :size="16" />
          Subir
        </AppButton>
        <code class="browser__path">{{ listing?.path || 'Unidades' }}</code>
      </div>

      <p v-if="failure" class="browser__error" role="alert">{{ failure }}</p>

      <ul v-if="listing" class="browser__list" :aria-busy="loading">
        <li v-for="dir in listing.dirs" :key="dir">
          <button type="button" class="entry" @click="go(dir)">
            <AppIcon name="folder" :size="18" />
            <span class="entry__name">{{ folderLabel(dir) }}</span>
          </button>
        </li>
        <template v-if="mode !== 'dir'">
          <li v-for="file in listing.files" :key="file.path">
            <button
              type="button"
              :class="['entry', { 'is-selected': selected.includes(file.path) }]"
              :aria-pressed="selected.includes(file.path)"
              @click="toggle(file.path)"
            >
              <AppIcon :name="selected.includes(file.path) ? 'check' : 'file'" :size="18" />
              <span class="entry__name">{{ file.name }}</span>
              <span class="entry__size">{{ formatSizeMb(file.size_mb) }}</span>
            </button>
          </li>
        </template>
        <li v-if="!listing.dirs.length && !(mode !== 'dir' && listing.files.length)" class="browser__empty">
          Nada para escolher nesta pasta.
        </li>
      </ul>
    </div>

    <template #footer>
      <span v-if="mode !== 'dir'" class="browser__count">
        {{ selected.length }} {{ selected.length === 1 ? 'selecionado' : 'selecionados' }}
      </span>
      <AppButton @click="open = false">Cancelar</AppButton>
      <AppButton variant="primary" :disabled="!canConfirm" @click="confirm">
        {{ mode === 'dir' ? 'Usar esta pasta' : 'Escolher' }}
      </AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.browser {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.browser__bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.browser__path {
  flex: 1;
  min-width: 0;
  padding: 0.4rem 0.75rem;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: var(--color-bg-soft);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-soft);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.browser__error {
  color: var(--color-error);
  font-size: var(--text-sm);
}

.browser__list {
  max-height: 22rem;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.entry {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  padding: 0.55rem var(--space-3);
  border: 0;
  border-bottom: 1px solid var(--color-border);
  background: transparent;
  text-align: left;
  font-size: var(--text-sm);
}

.entry:hover {
  background: var(--color-surface-hover);
}

.entry.is-selected {
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}

.entry__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry__size {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.browser__empty {
  padding: var(--space-5);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.browser__count {
  margin-right: auto;
  align-self: center;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}
</style>

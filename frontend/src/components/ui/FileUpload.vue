<script setup lang="ts">
/* Escolha de arquivos por botão ou arrastando para a área, um ou vários, com filtro de tipo e de tamanho.
   O componente só guarda a escolha: enviar ao servidor (speech/upload, fila, clonar voz) é com quem o usa. */
import { computed, ref, useId } from 'vue'
import { filterFiles, formatBytes, mergeFiles } from '@/lib/files'
import AppButton from './AppButton.vue'
import AppIcon from './AppIcon.vue'

const props = withDefaults(
  defineProps<{
    label: string
    /** Mesmo formato do `accept` do input: ".txt,.md", "audio/*,video/*". Vazio aceita tudo. */
    accept?: string
    multiple?: boolean
    hint?: string
    disabled?: boolean
    /** Um envio está em andamento: a área fica parada e mostra "Enviando". */
    busy?: boolean
    /** Recusa arquivos maiores que isto, em bytes. */
    maxBytes?: number
    buttonLabel?: string
    /** Mostra a lista de arquivos escolhidos com o botão de remover de cada um. */
    showList?: boolean
    /** Só o botão, sem a área tracejada e sem o texto de apoio (cabe numa barra de ações); arrastar sobre ele ainda vale. */
    compact?: boolean
    /** Como a recusa por tipo descreve o que se aceita, no lugar da lista do `accept` (que pode ser longa). */
    acceptLabel?: string
  }>(),
  { accept: '', showList: true, compact: false },
)

const files = defineModel<File[]>({ default: () => [] })
const emit = defineEmits<{ select: [files: File[]]; reject: [files: File[]] }>()

const labelId = `upload-label-${useId()}`
const input = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const problem = ref('')

const inactive = computed(() => props.disabled || props.busy)
const button = computed(() => props.buttonLabel ?? (props.multiple ? 'Escolher arquivos' : 'Escolher arquivo'))
const prompt = computed(() => (props.multiple ? 'ou arraste os arquivos para cá' : 'ou arraste o arquivo para cá'))

function receive(list: File[]): void {
  if (inactive.value || list.length === 0) return
  const { accepted, rejected, tooBig } = filterFiles(list, props.accept, props.maxBytes)

  const problems: string[] = []
  if (rejected.length) {
    problems.push(`Não aceitei ${rejected.map((file) => file.name).join(', ')}. Tipos aceitos: ${props.acceptLabel ?? props.accept}.`)
  }
  if (tooBig.length && props.maxBytes !== undefined) {
    problems.push(`${tooBig.map((file) => file.name).join(', ')}: maior que ${formatBytes(props.maxBytes)}.`)
  }
  problem.value = problems.join(' ')
  if (rejected.length || tooBig.length) emit('reject', [...rejected, ...tooBig])
  if (accepted.length === 0) return

  // vários: soma ao que já estava; um só: o novo arquivo troca o anterior
  const next = props.multiple ? mergeFiles(files.value, accepted) : accepted.slice(0, 1)
  files.value = next
  emit('select', next)
}

function onPick(event: Event): void {
  const target = event.target as HTMLInputElement
  receive(Array.from(target.files ?? []))
  target.value = '' // escolher o mesmo arquivo de novo precisa disparar a mudança outra vez
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  receive(Array.from(event.dataTransfer?.files ?? []))
}

function remove(index: number): void {
  files.value = files.value.filter((_, position) => position !== index)
  problem.value = ''
}
</script>

<template>
  <div :class="['upload', { 'upload--compact': compact }]">
    <span :id="labelId" :class="compact ? 'upload__sr-only' : 'field-label'">{{ label }}</span>
    <div
      :class="['upload__zone', { 'is-dragging': dragging, 'is-inactive': inactive }]"
      role="group"
      :aria-labelledby="labelId"
      @dragenter.prevent="dragging = !inactive"
      @dragover.prevent="dragging = !inactive"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <AppIcon name="upload" :size="22" class="upload__icon" />
      <div class="upload__actions">
        <AppButton size="sm" :disabled="disabled" :loading="busy" @click="input?.click()">{{ button }}</AppButton>
        <span class="upload__prompt">{{ busy ? 'Enviando...' : prompt }}</span>
      </div>
      <input
        ref="input"
        class="upload__input"
        type="file"
        :accept="accept || undefined"
        :multiple="multiple"
        :disabled="inactive"
        tabindex="-1"
        aria-hidden="true"
        @change="onPick"
      />
    </div>

    <ul v-if="showList && files.length" class="upload__files" :aria-label="`Arquivos escolhidos em ${label}`">
      <li v-for="(file, index) in files" :key="`${file.name}-${file.size}-${file.lastModified}`" class="upload__file">
        <AppIcon name="file" :size="16" />
        <span class="upload__name" :title="file.name">{{ file.name }}</span>
        <span class="upload__size">{{ formatBytes(file.size) }}</span>
        <button type="button" class="upload__remove" :aria-label="`Remover ${file.name}`" @click="remove(index)">
          <AppIcon name="x" :size="14" />
        </button>
      </li>
    </ul>

    <p v-if="hint" class="field-hint">{{ hint }}</p>
    <p v-if="problem" class="upload__problem" role="alert">{{ problem }}</p>
  </div>
</template>

<style scoped>
.upload {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
}

.upload__zone {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
  transition:
    border-color var(--transition),
    background var(--transition);
}

.upload__zone.is-dragging {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
}

.upload__zone.is-inactive {
  opacity: 0.7;
}

.upload__icon {
  flex-shrink: 0;
  color: var(--color-text-muted);
}

.upload__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.upload__prompt {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.upload__input {
  display: none;
}

.upload__files {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.upload__file {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  font-size: var(--text-sm);
}

.upload__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload__size {
  flex-shrink: 0;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.upload__remove {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 1.5rem;
  height: 1.5rem;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-soft);
}

.upload__remove:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.upload__problem {
  font-size: var(--text-xs);
  color: var(--color-error);
}

/* compacto: só o botão, para a barra de ações de uma caixa de mensagem; o nome do campo fica para quem usa leitor de tela */
.upload__sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.upload--compact .upload__zone {
  gap: 0;
  padding: 0;
  border: 0;
  background: transparent;
}

.upload--compact .upload__zone.is-dragging {
  background: var(--color-accent-bg);
}

.upload--compact .upload__icon,
.upload--compact .upload__prompt {
  display: none;
}
</style>

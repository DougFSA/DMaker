<script setup lang="ts">
/* Os marcadores do vídeo (a trilha MK da linha do tempo), um por linha: o texto, o grupo, o instante ou a região e a
   cor. Criar no cursor, arrastar e renomear também se faz direto na linha do tempo; aqui se corrige o número exato. */
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useEditorActions } from '@/composables/useEditorActions'
import { MARKER_FIELDS } from '@/lib/editorFields'
import { useEditorStore } from '@/stores/editor'
import EditorSection from './EditorSection.vue'
import FieldGrid from './FieldGrid.vue'

const open = defineModel<boolean>('open', { default: true })
const editor = useEditorStore()
const actions = useEditorActions()

const markers = computed(() => (editor.get('markers') as Array<Record<string, unknown>> | undefined) ?? [])

function isRegion(marker: Record<string, unknown>): boolean {
  return typeof marker.start === 'number'
}

function when(marker: Record<string, unknown>): string {
  const seconds = (value: unknown) => String(Math.round(Number(value) * 1000) / 1000).replace('.', ',')
  return isRegion(marker) ? `${seconds(marker.start)} a ${seconds(marker.end)} s` : `${seconds(marker.at)} s`
}

function fieldsOf(marker: Record<string, unknown>) {
  return isRegion(marker) ? [MARKER_FIELDS.start, MARKER_FIELDS.end] : [MARKER_FIELDS.at]
}

function colorOf(marker: Record<string, unknown>): string {
  return typeof marker.color === 'string' ? marker.color : '#d9a21b'
}

function setColor(index: number, event: Event): void {
  editor.setField(`markers.${index}.color`, (event.target as HTMLInputElement).value)
}

function remove(index: number): void {
  void editor.applyOp({ type: 'marker_remove', index })
}
</script>

<template>
  <EditorSection v-model:open="open" title="Marcadores" :count="markers.length">
    <template #actions>
      <AppButton size="sm" :disabled="!editor.view" @click="actions.addMarker()">Marcador no cursor</AppButton>
    </template>

    <p v-if="markers.length === 0" class="hint">
      Sem marcadores ainda. Aperte M na linha do tempo para marcar o cursor, ou importe o .txt do Audacity pela CLI
      (<code>dmaker markers import</code>). Os marcadores acompanham os cortes.
    </p>

    <ul class="markers">
      <li v-for="(marker, index) in markers" :key="index" class="marker">
        <details>
          <summary class="marker__summary" :data-marker-row="index">
            <span class="marker__swatch" :style="{ background: typeof marker.color === 'string' ? marker.color : undefined }" />
            <span class="marker__text">{{ marker.text || 'sem texto' }}</span>
            <span class="marker__when">{{ when(marker) }}</span>
            <span v-if="marker.group" class="marker__group">{{ marker.group }}</span>
          </summary>
          <div class="marker__body">
            <FieldGrid :fields="[MARKER_FIELDS.text, MARKER_FIELDS.group, ...fieldsOf(marker)]" :base="`markers.${index}`" />
            <label class="marker__color">
              Cor
              <input type="color" :value="colorOf(marker)" :aria-label="`Cor do marcador ${index + 1}`" @input="setColor(index, $event)" />
            </label>
            <AppButton variant="ghost" size="sm" :aria-label="`Remover o marcador ${index + 1}`" @click="remove(index)">Remover</AppButton>
          </div>
        </details>
      </li>
    </ul>
  </EditorSection>
</template>

<style scoped>
.hint {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.markers {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.marker {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.marker__summary {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  cursor: pointer;
}

.marker__swatch {
  flex: none;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-border-strong);
}

.marker__text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.marker__when,
.marker__group {
  flex: none;
  color: var(--color-text-soft);
}

.marker__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: 0 var(--space-3) var(--space-3);
}

.marker__color {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
}
</style>

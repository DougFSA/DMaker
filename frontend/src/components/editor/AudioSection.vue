<script setup lang="ts">
/* O áudio do projeto: música de fundo, ganho da voz, normalização, silenciar os clipes e as faixas externas. */
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { AUDIO_FIELDS, AUDIO_TRACK_VOLUME_FIELD, MUSIC_FIELDS, type FieldDef } from '@/lib/editorFields'
import { addAudioTrack, removeFromList, setMusicEnabled, sourceNames } from '@/lib/editorSpec'
import { useEditorStore } from '@/stores/editor'
import EditorSection from './EditorSection.vue'
import FieldGrid from './FieldGrid.vue'
import SpecField from './SpecField.vue'

const open = defineModel<boolean>('open', { default: true })
const editor = useEditorStore()

const musicOn = computed(() => !!editor.get('audio.music'))
const tracks = computed(() => (editor.get('audio.tracks') as Array<Record<string, unknown>> | undefined) ?? [])
const names = computed(() => (editor.spec ? sourceNames(editor.spec) : []))
const sourceChoices = computed(() => names.value.map((name) => ({ value: name, label: name })))
const trackSourceField: FieldDef = { key: 'source', label: 'Fonte', kind: 'select', def: 'AudioTrack' }

function removeTrack(index: number): void {
  editor.mutate((spec) => removeFromList(((spec.audio as Record<string, unknown>).tracks as unknown[]) ?? [], index))
}
</script>

<template>
  <EditorSection v-model:open="open" title="Áudio">
    <AppCheckbox
      :model-value="musicOn"
      label="Usar música de fundo"
      @update:model-value="editor.mutate((spec) => setMusicEnabled(spec, $event))"
    />
    <FieldGrid v-if="musicOn" :fields="MUSIC_FIELDS" base="audio" />

    <FieldGrid :fields="AUDIO_FIELDS" base="audio" />

    <fieldset class="sub">
      <legend>Faixas externas sincronizadas</legend>
      <p v-if="names.length === 0" class="hint">Cadastre uma fonte sincronizada acima para usar faixas externas.</p>
      <p v-else-if="tracks.length === 0" class="hint">Nenhuma faixa ainda.</p>
      <ul v-if="tracks.length" class="tracks">
        <li v-for="(_track, index) in tracks" :key="index" class="track">
          <FieldGrid>
            <SpecField :field="trackSourceField" :base="`audio.tracks.${index}`" :choices="sourceChoices" />
            <SpecField :field="AUDIO_TRACK_VOLUME_FIELD" :base="`audio.tracks.${index}`" />
          </FieldGrid>
          <AppButton variant="ghost" size="sm" icon-only :aria-label="`Remover a faixa ${index + 1}`" @click="removeTrack(index)">
            <AppIcon name="x" :size="16" />
          </AppButton>
        </li>
      </ul>
      <div>
        <AppButton size="sm" :disabled="names.length === 0" @click="editor.mutate((spec) => addAudioTrack(spec))">
          Adicionar faixa
        </AppButton>
      </div>
    </fieldset>
  </EditorSection>
</template>

<style scoped>
.sub {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  border: 0;
}

.sub legend {
  margin-bottom: var(--space-2);
  padding: 0;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.hint {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.tracks {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.track {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.track > :first-child {
  flex: 1;
}
</style>

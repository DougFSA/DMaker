<script setup lang="ts">
/* O crossfade do SOM no corte de entrada de um clipe (J-cut e L-cut): liga e desliga o campo `audio_crossfade` do clipe
   e mostra a duração e o tipo. A imagem continua trocando no quadro exato; o som cruza em volta do corte, metade antes e
   metade depois, com a sobra do arquivo de cada lado. Mora ao lado da transição de imagem, que é o outro jeito de editar
   o corte entre dois clipes. */
import { computed } from 'vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import { AUDIO_CROSSFADE_DURATION_FIELD, AUDIO_CROSSFADE_TYPE_FIELD } from '@/lib/editorFields'
import { useEditorStore } from '@/stores/editor'
import FieldGrid from './FieldGrid.vue'
import SpecField from './SpecField.vue'

const props = defineProps<{ index: number }>()

const editor = useEditorStore()

const base = computed(() => `timeline.${props.index}`)
const active = computed(() => {
  const value = editor.get(`${base.value}.audio_crossfade`)
  return typeof value === 'object' && value !== null
})
/** Com uma transição de imagem de verdade no corte, o `acrossfade` da montagem já cruza o som e o campo não vale. */
const imageTransition = computed(() => {
  const type = editor.get(`${base.value}.transition.type`)
  return typeof type === 'string' && type !== 'cut'
})

function toggle(on: boolean): void {
  editor.mutate((spec) => {
    const segment = (spec.timeline as Record<string, unknown>[])[props.index]
    if (!segment) return
    if (on) segment.audio_crossfade = { duration: 0.5, curve: 'constant_power_1' }
    else delete segment.audio_crossfade
  })
}
</script>

<template>
  <fieldset class="sub">
    <legend>Crossfade do som neste corte</legend>
    <AppCheckbox
      label="Cruzar o som deste clipe com o do anterior"
      hint="A imagem continua trocando no quadro exato do corte (J-cut e L-cut). O som de cada lado vem da sobra do arquivo além do ponto de entrada e do de saída; sem sobra, o cruzamento encurta."
      :model-value="active"
      @update:model-value="toggle"
    />
    <p v-if="active && imageTransition" class="note" data-crossfade-ignored="1">
      Este corte tem transição de imagem, que já cruza o som: o crossfade de som não vale. Ponha a transição em “cut” para usá-lo.
    </p>
    <FieldGrid v-if="active">
      <SpecField :field="AUDIO_CROSSFADE_DURATION_FIELD" :base="base" />
      <SpecField :field="AUDIO_CROSSFADE_TYPE_FIELD" :base="base" />
    </FieldGrid>
  </fieldset>
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

.note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}
</style>

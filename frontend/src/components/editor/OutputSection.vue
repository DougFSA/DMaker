<script setup lang="ts">
/* Saída do projeto: formato, qualidade, encoder, FPS, marca e as guias de zona segura. Com um formato só de áudio
   (audio/mp3...) a imagem sai de cena: aparecem a profundidade ou a taxa de bits, o volume de saída e as etiquetas. */
import { computed, onMounted } from 'vue'
import { isAudioPresetId } from '@/lib/audioExport'
import { BRAND_FIELD, OUTPUT_FIELDS, PRESET_FIELD } from '@/lib/editorFields'
import type { OptionItem } from '@/lib/editorLabels'
import { useCatalogStore } from '@/stores/catalog'
import { useEditorStore } from '@/stores/editor'
import { useToastsStore } from '@/stores/toasts'
import AudioOutputFields from './AudioOutputFields.vue'
import EditorSection from './EditorSection.vue'
import FieldGrid from './FieldGrid.vue'
import SpecField from './SpecField.vue'

const open = defineModel<boolean>('open', { default: true })
const catalog = useCatalogStore()
const toasts = useToastsStore()
const editor = useEditorStore()

onMounted(() => {
  catalog.load().catch(() => {
    toasts.push({ tone: 'error', title: 'Não consegui carregar os formatos e as marcas' })
  })
})

const presets = computed<OptionItem[]>(() => [
  ...catalog.presets.map((preset) => ({ value: preset.id, label: `${preset.platform} · ${preset.name} (${preset.id})` })),
  ...catalog.audioPresets.map((preset) => ({ value: preset.id, label: `Áudio · ${preset.name} (${preset.id})` })),
])
const audioOnly = computed(() => isAudioPresetId(editor.get('output.preset') as string | undefined))
const brands = computed<OptionItem[]>(() => catalog.brands.map((brand) => ({ value: brand.key, label: brand.name })))
</script>

<template>
  <EditorSection v-model:open="open" title="Saída">
    <FieldGrid>
      <SpecField :field="PRESET_FIELD" base="output" :choices="presets" />
      <template v-if="!audioOnly">
        <SpecField :field="OUTPUT_FIELDS.quality" base="output" />
        <SpecField :field="OUTPUT_FIELDS.encoder" base="output" />
        <SpecField :field="OUTPUT_FIELDS.fps" base="output" />
      </template>
      <SpecField :field="BRAND_FIELD" base="" :choices="brands" />
      <SpecField v-if="!audioOnly" :field="OUTPUT_FIELDS.guides" base="output" />
    </FieldGrid>
    <AudioOutputFields v-if="audioOnly" />
  </EditorSection>
</template>

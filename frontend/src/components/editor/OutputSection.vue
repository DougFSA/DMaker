<script setup lang="ts">
/* Saída do projeto: formato, qualidade, encoder, FPS, marca e as guias de zona segura. */
import { computed, onMounted } from 'vue'
import { BRAND_FIELD, OUTPUT_FIELDS, PRESET_FIELD } from '@/lib/editorFields'
import type { OptionItem } from '@/lib/editorLabels'
import { useCatalogStore } from '@/stores/catalog'
import { useToastsStore } from '@/stores/toasts'
import EditorSection from './EditorSection.vue'
import FieldGrid from './FieldGrid.vue'
import SpecField from './SpecField.vue'

const open = defineModel<boolean>('open', { default: true })
const catalog = useCatalogStore()
const toasts = useToastsStore()

onMounted(() => {
  catalog.load().catch(() => {
    toasts.push({ tone: 'error', title: 'Não consegui carregar os formatos e as marcas' })
  })
})

const presets = computed<OptionItem[]>(() =>
  catalog.presets.map((preset) => ({ value: preset.id, label: `${preset.platform} · ${preset.name} (${preset.id})` })),
)
const brands = computed<OptionItem[]>(() => catalog.brands.map((brand) => ({ value: brand.key, label: brand.name })))
</script>

<template>
  <EditorSection v-model:open="open" title="Saída">
    <FieldGrid>
      <SpecField :field="PRESET_FIELD" base="output" :choices="presets" />
      <SpecField :field="OUTPUT_FIELDS.quality" base="output" />
      <SpecField :field="OUTPUT_FIELDS.encoder" base="output" />
      <SpecField :field="OUTPUT_FIELDS.fps" base="output" />
      <SpecField :field="BRAND_FIELD" base="" :choices="brands" />
      <SpecField :field="OUTPUT_FIELDS.guides" base="output" />
    </FieldGrid>
  </EditorSection>
</template>

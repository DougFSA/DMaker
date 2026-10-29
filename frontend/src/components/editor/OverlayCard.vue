<script setup lang="ts">
/* Uma sobreposição (texto, imagem, vídeo em picture-in-picture ou barra de progresso) e os campos do tipo dela. */
import { computed, ref } from 'vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import {
  IMAGE_OVERLAY_FIELDS,
  PROGRESS_FIELDS,
  TEXT_OVERLAY_FIELDS,
  VIDEO_OVERLAY_FIELDS,
  type FieldDef,
} from '@/lib/editorFields'
import { LOGO_SOURCES } from '@/lib/editorLabels'
import {
  OVERLAY_TYPES,
  OVERLAY_TYPE_LABEL,
  convertOverlay,
  describeOverlay,
  duplicateInList,
  moveInList,
  removeFromList,
  type OverlayType,
} from '@/lib/editorSpec'
import { useEditorStore } from '@/stores/editor'
import FieldGrid from './FieldGrid.vue'
import FileField from './FileField.vue'
import ItemCardShell from './ItemCardShell.vue'
import MediaThumb from './MediaThumb.vue'
import SourceOriginField from './SourceOriginField.vue'
import SpecField from './SpecField.vue'

const CUSTOM_FILE = '__arquivo__'

const props = defineProps<{ index: number; overlay: Record<string, unknown>; count: number }>()
const expanded = defineModel<boolean>('expanded', { default: false })

const editor = useEditorStore()

const base = computed(() => `overlays.${props.index}`)
const type = computed(() => String(props.overlay.type ?? ''))
const knownType = computed(() => OVERLAY_TYPES.includes(type.value as OverlayType))
const typeOptions = computed(() => {
  const options = OVERLAY_TYPES.map((value) => ({ value, label: OVERLAY_TYPE_LABEL[value] }))
  return knownType.value ? options : [...options, { value: type.value, label: type.value }]
})
const usesSource = computed(() => typeof props.overlay.source === 'string' && props.overlay.source !== '')

const videoFields = computed<FieldDef[]>(() =>
  VIDEO_OVERLAY_FIELDS.map((field) =>
    field.key === 'offset'
      ? { ...field, label: usesSource.value ? 'Tempo de entrada na fonte (s)' : 'Ponto de entrada no arquivo (s)' }
      : field,
  ),
)

const thumb = computed<{ src: string; kind: 'video' | 'image' } | null>(() => {
  const src = props.overlay.src
  if (type.value === 'image' && typeof src === 'string' && src && !src.startsWith('logo')) return { src, kind: 'image' }
  if (type.value !== 'video') return null
  if (typeof src === 'string' && src) return { src, kind: 'video' }
  const fromSource = usesSource.value ? editor.get(`sources.${props.overlay.source as string}.src`) : null
  return typeof fromSource === 'string' && fromSource ? { src: fromSource, kind: 'video' } : null
})

/* ---- origem da imagem: uma das variantes do logo ou um arquivo ---- */

const logoValues = LOGO_SOURCES.map((option) => option.value)
const imageSrc = computed(() => (typeof props.overlay.src === 'string' ? props.overlay.src : ''))
const holdsFile = computed(() => imageSrc.value !== '' && !logoValues.includes(imageSrc.value))
const fileMode = ref(holdsFile.value)
const srcOptions = [...LOGO_SOURCES, { value: CUSTOM_FILE, label: 'Personalizado (arquivo)' }]
const srcChoice = computed(() => (fileMode.value || holdsFile.value ? CUSTOM_FILE : imageSrc.value || 'logo'))

function chooseImageSource(choice: string): void {
  if (choice === CUSTOM_FILE) {
    fileMode.value = true
    // sair de uma variante do logo deixa o campo do arquivo vazio, para a pessoa escolher
    if (!holdsFile.value) editor.setField(`${base.value}.src`, undefined)
    return
  }
  fileMode.value = false
  editor.setField(`${base.value}.src`, choice)
}

/* ---- ações ---- */

function changeType(next: string): void {
  if (!OVERLAY_TYPES.includes(next as OverlayType) || next === type.value) return
  editor.mutate((spec) => {
    ;(spec.overlays as unknown[])[props.index] = convertOverlay(props.overlay, next as OverlayType)
  })
}

function move(delta: -1 | 1): void {
  editor.mutate((spec) => moveInList(spec.overlays as unknown[], props.index, delta))
}

function duplicate(): void {
  editor.mutate((spec) => duplicateInList(spec.overlays as unknown[], props.index))
}

function remove(): void {
  editor.mutate((spec) => removeFromList(spec.overlays as unknown[], props.index))
}
</script>

<template>
  <ItemCardShell
    v-model:expanded="expanded"
    :position="index + 1"
    noun="sobreposição"
    feminine
    :summary="describeOverlay(overlay)"
    :type="type"
    :type-options="typeOptions"
    :can-move-up="index > 0"
    :can-move-down="index < count - 1"
    @change-type="changeType"
    @up="move(-1)"
    @down="move(1)"
    @duplicate="duplicate"
    @remove="remove"
  >
    <MediaThumb v-if="thumb" :src="thumb.src" :kind="thumb.kind" />

    <p v-if="!knownType" class="note">
      Esta sobreposição (“{{ type }}”) não tem formulário: edite na aba JSON. Os campos dela são preservados ao salvar.
    </p>

    <FieldGrid v-else-if="type === 'text'" :fields="TEXT_OVERLAY_FIELDS" :base="base" />

    <FieldGrid v-else-if="type === 'image'" :base="base">
      <AppSelect label="Origem" :model-value="srcChoice" :options="srcOptions" @update:model-value="chooseImageSource" />
      <FileField
        v-if="srcChoice === CUSTOM_FILE"
        label="Arquivo"
        :model-value="holdsFile ? imageSrc : ''"
        @update:model-value="editor.setField(`${base}.src`, $event || undefined)"
      />
      <SpecField v-for="field in IMAGE_OVERLAY_FIELDS" :key="field.key" :field="field" :base="base" />
    </FieldGrid>

    <FieldGrid v-else-if="type === 'video'" :base="base">
      <SourceOriginField
        :base="base"
        source-hint="Início e fim ficam na linha do tempo; o ponto de entrada é o tempo, no relógio da fonte principal, em que a sobreposição entra nesta fonte."
      />
      <SpecField v-for="field in videoFields" :key="field.key" :field="field" :base="base" />
    </FieldGrid>

    <FieldGrid v-else :fields="PROGRESS_FIELDS" :base="base" />
  </ItemCardShell>
</template>

<style scoped>
.note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}
</style>

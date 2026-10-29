<script setup lang="ts">
/* Um trecho da linha do tempo (clipe, imagem ou cartão): os campos do tipo, a transição de entrada e o enquadramento. */
import { computed } from 'vue'
import {
  CARD_FIELDS,
  CLIP_FIELDS,
  IMAGE_FIELDS,
  REFRAME_FOCUS_FIELDS,
  REFRAME_MODE_FIELD,
  SEGMENT_LABEL_FIELD,
  TRANSITION_DURATION_FIELD,
  TRANSITION_TYPE_FIELD,
} from '@/lib/editorFields'
import { transitionItems } from '@/lib/editorLabels'
import {
  SEGMENT_TYPES,
  SEGMENT_TYPE_LABEL,
  convertSegment,
  describeSegment,
  duplicateInList,
  moveInList,
  removeFromList,
  type SegmentType,
} from '@/lib/editorSpec'
import { useEditorStore } from '@/stores/editor'
import { useToastsStore } from '@/stores/toasts'
import FieldGrid from './FieldGrid.vue'
import ItemCardShell from './ItemCardShell.vue'
import MediaThumb from './MediaThumb.vue'
import SourceOriginField from './SourceOriginField.vue'
import SpecField from './SpecField.vue'

const props = defineProps<{ index: number; segment: Record<string, unknown>; count: number }>()
const expanded = defineModel<boolean>('expanded', { default: false })

const editor = useEditorStore()
const toasts = useToastsStore()

const base = computed(() => `timeline.${props.index}`)
const type = computed(() => String(props.segment.type ?? ''))
const knownType = computed(() => SEGMENT_TYPES.includes(type.value as SegmentType))
const typeOptions = computed(() => {
  const options = SEGMENT_TYPES.map((value) => ({ value, label: SEGMENT_TYPE_LABEL[value] }))
  // um tipo que o formulário não conhece continua visível no seletor (só não dá para trocar para ele)
  return knownType.value ? options : [...options, { value: type.value, label: type.value }]
})
const typeFields = computed(() => (type.value === 'clip' ? CLIP_FIELDS : type.value === 'image' ? IMAGE_FIELDS : CARD_FIELDS))
const cropping = computed(() => (editor.get(`${base.value}.reframe.mode`) ?? 'auto') === 'crop')
const transitions = computed(() => transitionItems(editor.transitions))

const thumb = computed<{ src: string; kind: 'video' | 'image' } | null>(() => {
  const src = props.segment.src
  if (type.value === 'image' && typeof src === 'string' && src) return { src, kind: 'image' }
  if (type.value !== 'clip') return null
  if (typeof src === 'string' && src) return { src, kind: 'video' }
  const source = props.segment.source
  const fromSource = typeof source === 'string' ? editor.get(`sources.${source}.src`) : null
  return typeof fromSource === 'string' && fromSource ? { src: fromSource, kind: 'video' } : null
})

function changeType(next: string): void {
  if (!SEGMENT_TYPES.includes(next as SegmentType) || next === type.value) return
  editor.mutate((spec) => {
    ;(spec.timeline as unknown[])[props.index] = convertSegment(props.segment, next as SegmentType)
  })
}

function move(delta: -1 | 1): void {
  editor.mutate((spec) => moveInList(spec.timeline as unknown[], props.index, delta))
}

function duplicate(): void {
  editor.mutate((spec) => duplicateInList(spec.timeline as unknown[], props.index))
}

function remove(): void {
  const removed = editor.mutate((spec) => removeFromList(spec.timeline as unknown[], props.index, 1))
  if (removed === false) {
    toasts.push({ tone: 'error', title: 'É preciso manter ao menos um trecho na linha do tempo' })
  }
}
</script>

<template>
  <ItemCardShell
    v-model:expanded="expanded"
    :position="index + 1"
    noun="trecho"
    :summary="describeSegment(segment)"
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
      Este tipo de trecho (“{{ type }}”) não tem formulário: edite na aba JSON.
    </p>
    <template v-else>
      <FieldGrid>
        <SpecField :field="SEGMENT_LABEL_FIELD" :base="base" />
        <SourceOriginField
          v-if="type === 'clip'"
          :base="base"
          source-hint="Início e fim no relógio da fonte principal."
        />
        <SpecField v-for="field in typeFields" :key="field.key" :field="field" :base="base" />
      </FieldGrid>

      <fieldset class="sub">
        <legend>Transição de entrada</legend>
        <FieldGrid>
          <SpecField :field="TRANSITION_TYPE_FIELD" :base="base" :choices="transitions" />
          <SpecField :field="TRANSITION_DURATION_FIELD" :base="base" />
        </FieldGrid>
      </fieldset>

      <fieldset class="sub">
        <legend>Enquadramento</legend>
        <FieldGrid>
          <SpecField :field="REFRAME_MODE_FIELD" :base="base" />
          <template v-if="cropping">
            <SpecField v-for="field in REFRAME_FOCUS_FIELDS" :key="field.key" :field="field" :base="base" />
          </template>
        </FieldGrid>
      </fieldset>
    </template>
  </ItemCardShell>
</template>

<style scoped>
.note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

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
</style>

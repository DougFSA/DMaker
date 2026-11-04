<script setup lang="ts">
/* A janela do efeito na seleção: o efeito escolhido do catálogo do servidor, os parâmetros montados sozinhos a partir dele,
   a "Prévia" (toca os primeiros segundos da seleção com o efeito, sem gravar nada) e a alternância Antes e Depois, que
   troca o que se escuta sem interromper nem deslocar o som. Aplicar grava o efeito na spec com o intervalo da seleção. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { errorMessage } from '@/api'
import type { AudioEffectInfo, AudioEffectSettings, AudioEffectValue } from '@/api'
import { fetchEffectPreview, fetchWindow } from '@/api/audioPanel'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import { ComparePlayer, type CompareSide } from '@/lib/audioCompare'
import { newAudioContext } from '@/lib/audioContext'
import { effectsFor, newEffect, targetMayGrow } from '@/lib/audioEffects'
import { PREVIEW_SECONDS, SPECTRAL_PREFIX } from '@/lib/audioPanelOps'
import { formatHz } from '@/lib/spectrogram'
import { formatSpan } from '@/lib/audioWave'
import { pruneEmpty } from '@/lib/editorPaths'
import { useAudioEffectsStore } from '@/stores/audioEffects'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { useEditorStore } from '@/stores/editor'
import SavePresetButton from '../SavePresetButton.vue'
import AudioEffectForm from './AudioEffectForm.vue'

const emit = defineEmits<{ 'preview-start': [] }>()
const open = defineModel<boolean>('open', { default: false })

/** Quanto esperar a pessoa parar de mexer num parâmetro antes de refazer a prévia que está tocando. */
const REPREVIEW_DELAY_MS = 600

const panel = useAudioPanelStore()
const editor = useEditorStore()
const catalog = useAudioEffectsStore()

const type = ref('')
const values = ref<Record<string, AudioEffectValue>>({})
const side = ref<CompareSide>('after')
const status = ref<'idle' | 'loading' | 'playing'>('idle')
const problem = ref('')
const exact = ref(true)
const note = ref('')
let compare: ComparePlayer | null = null
let previewed = false
let reTimer: ReturnType<typeof setTimeout> | null = null
let ticket = 0

/** O lugar da cadeia como o catálogo o escreve (`audio.voiceover.N`), para saber se o efeito pode crescer o item. */
const genericTarget = computed(() => panel.target?.replace(/\.\d+$/, '.N') ?? '')
/** Só uma seleção com frequência (o retângulo do espectrograma) pede os efeitos espectrais: eles agem numa faixa. */
const hasBand = computed(() => panel.selection?.low_hz !== undefined || panel.selection?.high_hz !== undefined)
const offered = computed<AudioEffectInfo[]>(() => [
  ...effectsFor(catalog.effects, targetMayGrow(catalog.targets, genericTarget.value)),
  ...(hasBand.value ? catalog.effects.filter((info) => info.type.startsWith(SPECTRAL_PREFIX)) : []),
])
const info = computed(() => offered.value.find((candidate) => candidate.type === type.value) ?? null)
const typeOptions = computed(() => offered.value.map((effect) => ({ value: effect.type, label: effect.label })))

const selectionText = computed(() => {
  const selection = panel.selection
  if (!selection) return 'o item inteiro (sem seleção)'
  const band = selection.low_hz !== undefined && selection.high_hz !== undefined ? `, de ${formatHz(selection.low_hz)} a ${formatHz(selection.high_hz)}` : ''
  return `a seleção, de ${formatSpan(selection.start)} a ${formatSpan(selection.end)}${band}`
})

/** A janela que a prévia toca: o começo da seleção ou, sem ela, do cursor. */
const previewRange = computed(() => {
  const selection = panel.selection
  if (selection) return { start: selection.start, end: Math.min(selection.end, selection.start + PREVIEW_SECONDS) }
  const start = panel.cursor >= panel.duration - 0.05 ? 0 : panel.cursor
  return { start, end: Math.min(start + PREVIEW_SECONDS, panel.duration) }
})

/** O efeito que a janela mostra ao abrir: com um retângulo de frequência, o Apagar espectral; senão o Normalizar. */
function firstEffect(list: readonly AudioEffectInfo[]): string {
  const wanted = hasBand.value ? 'spectral_delete' : 'normalize'
  return (list.find((effect) => effect.type === wanted) ?? list[0])?.type ?? ''
}

function resetValues(): void {
  const chosen = info.value
  const draft: Record<string, AudioEffectValue> = {}
  if (chosen) {
    for (const [key, value] of Object.entries(newEffect(chosen))) {
      if (key !== 'type' && (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string')) draft[key] = value
      // as listas do EQ (31 ganhos, pontos da curva) vão por cópia: mexer no rascunho não mexe no catálogo
      else if (key !== 'type' && Array.isArray(value)) draft[key] = JSON.parse(JSON.stringify(value))
    }
  }
  // a faixa de frequência do retângulo preenche os campos dos efeitos espectrais; dá para ajustar à mão
  const selection = panel.selection
  if (chosen?.type.startsWith(SPECTRAL_PREFIX) && selection) {
    if (selection.low_hz !== undefined) draft.low_hz = selection.low_hz
    if (selection.high_hz !== undefined) draft.high_hz = selection.high_hz
  }
  values.value = draft
}

watch(open, (isOpen) => {
  if (!isOpen) {
    stopPreview()
    return
  }
  void catalog.load()
  problem.value = ''
  note.value = ''
  previewed = false
  if (hasBand.value && !type.value.startsWith(SPECTRAL_PREFIX)) {
    type.value = 'spectral_delete'
  } else if (!offered.value.some((effect) => effect.type === type.value)) {
    type.value = firstEffect(offered.value)
  }
  resetValues()
})
watch(offered, (list) => {
  if (!open.value) return
  // o catálogo pode chegar depois de a janela abrir (e o efeito escolhido só passa a existir então): os valores saem dele
  if (!list.some((effect) => effect.type === type.value)) type.value = firstEffect(list)
  resetValues()
})
watch(type, () => {
  resetValues()
  previewed = false
  stopPreview()
})
watch(side, (next) => compare?.switchTo(next))
// mexer num parâmetro com a prévia tocando refaz a prévia sozinho, depois de a pessoa parar de mexer
watch(
  values,
  () => {
    if (!previewed || !open.value) return
    if (reTimer) clearTimeout(reTimer)
    reTimer = setTimeout(() => void runPreview(), REPREVIEW_DELAY_MS)
  },
  { deep: true },
)

function stopPreview(): void {
  ticket += 1
  if (reTimer) clearTimeout(reTimer)
  reTimer = null
  compare?.stop()
  status.value = 'idle'
}

function proposedEffect(): AudioEffectSettings {
  const selection = panel.selection
  return {
    type: type.value,
    ...values.value,
    ...(selection ? { start: selection.start, end: selection.end } : {}),
  }
}

async function runPreview(): Promise<void> {
  const name = editor.name
  const target = panel.target
  const spec = editor.spec
  if (!name || !target || !spec || !info.value) return
  editor.flushPendingEdits()
  emit('preview-start')
  const mine = ++ticket
  status.value = 'loading'
  problem.value = ''
  const { start, end } = previewRange.value
  const body = pruneEmpty(spec)
  try {
    const [before, after] = await Promise.all([
      fetchWindow(name, body, target, start, end),
      fetchEffectPreview(name, body, target, proposedEffect(), start, end),
    ])
    if (mine !== ticket) return
    compare ??= new ComparePlayer(newAudioContext)
    await compare.load(before.data, after.data)
    if (mine !== ticket) return
    exact.value = after.exact
    note.value = after.note
    previewed = true
    await compare.play(side.value)
    status.value = 'playing'
  } catch (failure) {
    if (mine !== ticket) return
    problem.value = errorMessage(failure)
    status.value = 'idle'
  }
}

async function apply(): Promise<void> {
  if (!info.value) return
  stopPreview()
  const done = await panel.applyEffect(info.value.type, { ...values.value })
  if (done) open.value = false
}

onBeforeUnmount(() => {
  stopPreview()
  compare?.dispose()
  compare = null
})
</script>

<template>
  <AppDialog v-model:open="open" title="Aplicar efeito" description="O efeito vale para a seleção e fica na cadeia do item: dá para desligá-lo, mudá-lo ou tirá-lo depois." size="md">
    <div class="dialog-body" data-audio-effect-dialog>
      <p v-if="!catalog.loaded && catalog.error" class="dialog-body__warn" role="status">
        Não foi possível carregar o catálogo de efeitos: {{ catalog.error }}
      </p>
      <AppSelect v-model="type" label="Efeito" :options="typeOptions" data-effect-type />
      <template v-if="info">
        <p class="dialog-body__summary" data-effect-summary>
          {{ info.summary }}
          <span v-if="info.audacity_name !== info.label" class="dialog-body__audacity">No Audacity: {{ info.audacity_name }}.</span>
        </p>
        <p class="dialog-body__range" data-effect-range>Vale para {{ selectionText }}.</p>
        <AudioEffectForm v-model="values" :info="info" />
      </template>

      <section class="ab" aria-label="Prévia e comparação antes e depois">
        <div class="ab__row">
          <AppButton size="sm" :loading="status === 'loading'" :disabled="!info" data-effect-preview @click="runPreview">
            {{ status === 'playing' ? 'Refazer a prévia' : 'Prévia' }}
          </AppButton>
          <SegmentedControl v-model="side" label="Ouvir" :options="[{ value: 'before', label: 'Antes' }, { value: 'after', label: 'Depois' }]" />
          <AppButton size="sm" variant="ghost" :disabled="status !== 'playing'" data-effect-stop @click="stopPreview">Parar</AppButton>
        </div>
        <p class="ab__hint">
          Toca {{ formatSpan(previewRange.end - previewRange.start) }} a partir de {{ formatSpan(previewRange.start) }}, em loop. Trocar entre Antes e Depois não interrompe o som.
        </p>
        <p v-if="note" class="dialog-body__warn" role="status" data-effect-note>{{ note }}</p>
        <p v-if="problem" class="dialog-body__error" role="alert" data-effect-problem>{{ problem }}</p>
      </section>
    </div>
    <template #footer>
      <SavePresetButton v-if="info" class="dialog-footer__preset" :effect="proposedEffect()" :suggestion="info.label" />
      <AppButton @click="open = false">Cancelar</AppButton>
      <AppButton variant="primary" :disabled="!info || panel.busy" data-effect-apply @click="apply">Aplicar</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
/* a predefinição fica à esquerda do rodapé; Cancelar e Aplicar seguem à direita */
.dialog-footer__preset {
  margin-right: auto;
}

.dialog-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.dialog-body__summary,
.dialog-body__range,
.ab__hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.dialog-body__audacity {
  color: var(--color-text-muted);
}

.dialog-body__warn {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-warning-bg);
  color: var(--color-warning);
  font-size: var(--text-sm);
}

.dialog-body__error {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-error-bg);
  color: var(--color-error);
  font-size: var(--text-sm);
}

.ab {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.ab__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}
</style>

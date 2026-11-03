<script setup lang="ts">
/* Exporta só o áudio do projeto: o formato do arquivo (WAV, MP3, FLAC, OGG, Opus, M4A, AIFF), o alvo de loudness e se
   sai o projeto inteiro, um arquivo por região de marcador, um por trilha ou só um trecho. Não renderiza nada sozinho:
   entrega o pedido pronto (`submit`) a quem chama, que o manda à API e confirma antes de trocar um arquivo. */
import { computed, ref, watch } from 'vue'
import type { AudioExportRequest } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import {
  bitrateModeLabel,
  buildAudioExportRequest,
  CHANNEL_OPTIONS,
  emptyForm,
  EXPORT_MODES,
  formatControls,
  isAudioPresetId,
  loudnessOptions,
  STEM_TRACKS,
} from '@/lib/audioExport'
import { useCatalogStore } from '@/stores/catalog'

const props = defineProps<{
  projectName: string
  /** O formato que a janela abre escolhido: o do projeto, se ele já é de áudio. */
  currentPreset?: string | null
  busy?: boolean
}>()
const emit = defineEmits<{ submit: [request: AudioExportRequest] }>()
const open = defineModel<boolean>('open', { default: false })

const catalog = useCatalogStore()
const form = ref(emptyForm())
const failure = ref('')

const presetOptions = computed(() => catalog.audioPresets.map((item) => ({ value: item.id, label: `${item.name} (${item.id})` })))
const selected = computed(() => catalog.audioPresets.find((item) => item.id === form.value.preset))
const controls = computed(() => formatControls(selected.value, form.value.bitrateMode))
const loudness = computed(() => loudnessOptions(catalog.loudnessTargets))
const depthOptions = computed(() =>
  controls.value.bitDepths.map((depth) => ({ value: String(depth), label: depth === 32 ? '32 bits (ponto flutuante)' : `${depth} bits` })),
)
const modeOptions = computed(() =>
  controls.value.bitrateModes.map((mode) => ({ value: mode, label: bitrateModeLabel(mode) })),
)
const rateOptions = computed(() => controls.value.sampleRates.map((rate) => ({ value: String(rate), label: `${rate / 1000} kHz` })))

watch(open, (isOpen) => {
  if (!isOpen) return
  failure.value = ''
  void catalog.load().then(() => {
    const keep = form.value.preset
    const wanted = isAudioPresetId(props.currentPreset) ? props.currentPreset : null
    form.value = { ...emptyForm(), preset: keep || wanted || catalog.audioPresets[0]?.id || '' }
  })
})

// trocar de formato apaga as escolhas que só valiam no anterior (24 bits não existe no MP3)
watch(
  () => form.value.preset,
  () => {
    form.value = { ...form.value, bitDepth: '', bitrateMode: '', bitrateK: '', quality: '', sampleRate: '' }
  },
)

function toggleTrack(track: string, on: boolean): void {
  const tracks = on ? [...form.value.tracks, track] : form.value.tracks.filter((item) => item !== track)
  form.value = { ...form.value, tracks }
}

function submit(): void {
  const built = buildAudioExportRequest(form.value)
  failure.value = built.error ?? ''
  if (built.request) emit('submit', built.request)
}
</script>

<template>
  <AppDialog
    v-model:open="open"
    title="Exportar áudio"
    :description="`Projeto ${props.projectName}. Grava só o som, sem imagem nenhuma.`"
    size="lg"
  >
    <form id="audio-export-form" class="form" @submit.prevent="submit">
      <div class="row">
        <AppSelect v-model="form.preset" label="Formato do arquivo" :options="presetOptions" :hint="selected?.notes" />
        <AppSelect
          v-model="form.loudness"
          label="Volume de saída"
          placeholder="Como está no projeto"
          :options="loudness"
          hint="Normaliza o arquivo para o alvo escolhido."
        />
      </div>

      <fieldset class="options">
        <legend class="field-label">O que exportar</legend>
        <label v-for="item in EXPORT_MODES" :key="item.value" :class="['mode', { 'is-on': form.mode === item.value }]">
          <input v-model="form.mode" type="radio" name="audio-mode" :value="item.value" />
          <span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.hint }}</small>
          </span>
        </label>
      </fieldset>

      <div v-if="form.mode === 'regions'" class="row">
        <AppInput v-model="form.group" label="Só o grupo (opcional)" placeholder="todos os grupos" />
        <div class="checks">
          <AppCheckbox v-model="form.pauses" label="Exportar também as pausas entre as regiões" />
          <AppCheckbox v-model="form.numbered" label="Número na frente do nome do arquivo" />
        </div>
      </div>

      <fieldset v-if="form.mode === 'stems'" class="options">
        <legend class="field-label">Trilhas (nenhuma marcada = todas as que o projeto tem)</legend>
        <AppCheckbox
          v-for="track in STEM_TRACKS"
          :key="track.id"
          :label="`${track.label} (${track.id})`"
          :model-value="form.tracks.includes(track.id)"
          @update:model-value="toggleTrack(track.id, $event)"
        />
      </fieldset>

      <div v-if="form.mode === 'selection'" class="row">
        <AppInput v-model="form.start" label="Começa em" placeholder="12,5 ou marker:Introdução" />
        <AppInput v-model="form.end" label="Termina em (opcional)" placeholder="o fim do projeto" />
      </div>

      <div v-if="selected" class="row">
        <AppSelect
          v-if="depthOptions.length"
          v-model="form.bitDepth"
          label="Profundidade"
          :placeholder="`Do formato (${selected.default_label})`"
          :options="depthOptions"
        />
        <AppSelect
          v-if="modeOptions.length > 1"
          v-model="form.bitrateMode"
          label="Modo da taxa de bits"
          placeholder="Do formato"
          :options="modeOptions"
        />
        <AppInput
          v-if="controls.usesBitrate"
          v-model="form.bitrateK"
          label="Taxa de bits (kbps)"
          :placeholder="selected.bitrate_k ? String(selected.bitrate_k) : ''"
          inputmode="numeric"
        />
        <AppInput
          v-if="controls.usesQuality"
          v-model="form.quality"
          :label="`Qualidade (${selected.quality_range[0]} a ${selected.quality_range[1]})`"
          :placeholder="selected.quality !== null ? String(selected.quality) : ''"
          inputmode="decimal"
        />
        <AppSelect
          v-if="rateOptions.length"
          v-model="form.sampleRate"
          label="Taxa de amostragem"
          placeholder="Do formato"
          :options="rateOptions"
        />
        <AppInput v-else v-model="form.sampleRate" label="Taxa de amostragem (Hz)" placeholder="48000" inputmode="numeric" />
        <AppSelect v-model="form.channels" label="Canais" :options="CHANNEL_OPTIONS.slice(1)" placeholder="Do formato" />
      </div>

      <p v-if="failure" class="form__error" role="alert">{{ failure }}</p>
    </form>

    <template #footer>
      <AppButton @click="open = false">Cancelar</AppButton>
      <AppButton variant="primary" type="submit" form="audio-export-form" :loading="busy">Exportar</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: var(--space-3);
  align-items: start;
}

.options {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  border: 0;
}

.checks {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  align-self: end;
}

.mode {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition:
    border-color var(--transition),
    background var(--transition);
}

.mode:hover {
  border-color: var(--color-border-strong);
}

.mode.is-on {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
}

.mode input {
  margin-top: 0.3rem;
  accent-color: var(--color-accent);
}

.mode strong {
  display: block;
  font-size: var(--text-md);
}

.mode small {
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}

.form__error {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  background: var(--color-error-bg);
  color: var(--color-error);
  font-size: var(--text-sm);
}
</style>

<script setup lang="ts">
/* Os campos da saída quando o formato é só de áudio: como o arquivo é gravado (profundidade ou taxa de bits), o volume de
   saída (os alvos usuais de loudness) e as etiquetas do arquivo (artista, título, álbum...). Lê e grava na spec pelo
   store do editor, como os outros campos; o que o formato não aceita nem aparece. */
import { computed } from 'vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import {
  bitrateModeLabel,
  CHANNEL_OPTIONS,
  formatControls,
  loudnessName,
  loudnessOptions,
} from '@/lib/audioExport'
import { useCatalogStore } from '@/stores/catalog'
import { useEditorStore } from '@/stores/editor'
import FieldGrid from './FieldGrid.vue'

const editor = useEditorStore()
const catalog = useCatalogStore()

const preset = computed(() => catalog.audioPresets.find((item) => item.id === editor.get('output.preset')))
const mode = computed(() => text('output.audio_format.bitrate_mode'))
const controls = computed(() => formatControls(preset.value, mode.value))

function text(path: string): string {
  const value = editor.get(path)
  return value === undefined || value === null ? '' : String(value)
}

/** Grava o campo; vazio apaga a chave (o padrão do formato volta a valer). */
function write(path: string, value: string, numeric = false): void {
  const trimmed = value.trim()
  if (!trimmed) return editor.setField(path, undefined)
  const number = Number(trimmed.replace(',', '.'))
  editor.setField(path, numeric && Number.isFinite(number) ? number : trimmed)
}

const depthOptions = computed(() =>
  controls.value.bitDepths.map((depth) => ({ value: String(depth), label: depth === 32 ? '32 bits (ponto flutuante)' : `${depth} bits` })),
)
const modeOptions = computed(() => controls.value.bitrateModes.map((item) => ({ value: item, label: bitrateModeLabel(item) })))
const rateOptions = computed(() => controls.value.sampleRates.map((rate) => ({ value: String(rate), label: `${rate / 1000} kHz` })))
const targets = computed(() => loudnessOptions(catalog.loudnessTargets))
const loudness = computed(() => loudnessName(catalog.loudnessTargets, editor.get('audio.target_lufs')))

const TAGS: Array<{ key: string; label: string }> = [
  { key: 'artist', label: 'Artista' },
  { key: 'title', label: 'Título' },
  { key: 'album', label: 'Álbum' },
  { key: 'track', label: 'Faixa' },
  { key: 'year', label: 'Ano' },
  { key: 'genre', label: 'Gênero' },
  { key: 'comment', label: 'Comentário' },
]
</script>

<template>
  <FieldGrid>
    <AppSelect
      v-if="depthOptions.length"
      :model-value="text('output.audio_format.bit_depth')"
      label="Profundidade"
      :placeholder="`Do formato (${preset?.default_label})`"
      :options="depthOptions"
      @update:model-value="write('output.audio_format.bit_depth', $event, true)"
    />
    <AppSelect
      v-if="modeOptions.length > 1"
      :model-value="mode"
      label="Modo da taxa de bits"
      placeholder="Do formato"
      :options="modeOptions"
      @update:model-value="write('output.audio_format.bitrate_mode', $event)"
    />
    <AppInput
      v-if="controls.usesBitrate"
      :model-value="text('output.audio_format.bitrate_k')"
      label="Taxa de bits (kbps)"
      :placeholder="preset?.bitrate_k ? String(preset.bitrate_k) : ''"
      inputmode="numeric"
      @update:model-value="write('output.audio_format.bitrate_k', $event, true)"
    />
    <AppInput
      v-if="controls.usesQuality"
      :model-value="text('output.audio_format.quality')"
      :label="`Qualidade (${preset?.quality_range[0]} a ${preset?.quality_range[1]})`"
      :placeholder="preset?.quality !== null && preset?.quality !== undefined ? String(preset.quality) : ''"
      inputmode="decimal"
      @update:model-value="write('output.audio_format.quality', $event, true)"
    />
    <AppSelect
      v-if="rateOptions.length"
      :model-value="text('output.audio_format.sample_rate')"
      label="Taxa de amostragem"
      placeholder="Do formato"
      :options="rateOptions"
      @update:model-value="write('output.audio_format.sample_rate', $event, true)"
    />
    <AppInput
      v-else
      :model-value="text('output.audio_format.sample_rate')"
      label="Taxa de amostragem (Hz)"
      :placeholder="preset ? String(preset.sample_rate) : ''"
      inputmode="numeric"
      @update:model-value="write('output.audio_format.sample_rate', $event, true)"
    />
    <AppSelect
      :model-value="text('output.audio_format.channels')"
      label="Canais"
      placeholder="Do formato"
      :options="CHANNEL_OPTIONS.slice(1)"
      @update:model-value="write('output.audio_format.channels', $event, true)"
    />
    <AppSelect
      :model-value="loudness"
      label="Volume de saída"
      :placeholder="`Personalizado (${text('audio.target_lufs') || '-14'} LUFS)`"
      :options="targets"
      hint="Normaliza o arquivo para o alvo escolhido (audio.target_lufs)."
      @update:model-value="editor.setField('audio.target_lufs', catalog.loudnessTargets[$event])"
    />
  </FieldGrid>
  <h4 class="tags__title">Etiquetas do arquivo</h4>
  <FieldGrid>
    <AppInput
      v-for="tag in TAGS"
      :key="tag.key"
      :model-value="text(`output.metadata.${tag.key}`)"
      :label="tag.label"
      @update:model-value="write(`output.metadata.${tag.key}`, $event)"
    />
  </FieldGrid>
</template>

<style scoped>
.tags__title {
  margin: var(--space-4) 0 var(--space-2);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-soft);
}
</style>

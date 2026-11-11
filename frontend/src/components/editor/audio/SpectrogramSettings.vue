<script setup lang="ts">
/* Os controles do espectrograma num popover da vista: escala, cores, faixa de frequência, janela e tamanho, ganho e
   alcance. Cada mudança vai para o store do painel (que a lembra) e a imagem é pedida de novo, menos a cor, que só repinta. */
import { computed, ref } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import {
  DEFAULT_SPECTROGRAM,
  SCALE_OPTIONS,
  SCHEME_OPTIONS,
  WINDOW_OPTIONS,
  WINDOW_SIZES,
  type ColorScheme,
  type SpectrogramScale,
} from '@/lib/spectrogram'
import { useAudioPanelStore } from '@/stores/audioPanel'

const panel = useAudioPanelStore()
const open = ref(false)
const settings = computed(() => panel.spectrogram)
const sizeOptions = WINDOW_SIZES.map((size) => ({ value: String(size), label: `${size} amostras` }))

/** Um número vazio ou fora de sentido volta ao padrão em vez de quebrar o pedido. */
function number(value: number | null, fallback: number): number {
  return value === null || Number.isNaN(value) ? fallback : value
}
</script>

<template>
  <div class="settings" @mousedown.stop @dblclick.stop @wheel.stop>
    <AppButton size="sm" :aria-expanded="open" data-spectrogram-settings-toggle title="Ajustes do espectrograma" @click="open = !open">Ajustes</AppButton>
    <div v-if="open" class="settings__panel" role="group" aria-label="Ajustes do espectrograma" data-spectrogram-settings>
      <AppSelect label="Escala" :model-value="settings.scale" :options="SCALE_OPTIONS" data-spectrogram-scale @update:model-value="panel.setSpectrogram({ scale: $event as SpectrogramScale })" />
      <AppSelect label="Cores" :model-value="settings.scheme" :options="SCHEME_OPTIONS" data-spectrogram-scheme @update:model-value="panel.setSpectrogram({ scheme: $event as ColorScheme })" />
      <AppNumberInput label="Frequência mínima" unit="Hz" :min="0" :model-value="settings.minHz" data-spectrogram-min @update:model-value="panel.setSpectrogram({ minHz: number($event, DEFAULT_SPECTROGRAM.minHz) })" />
      <AppNumberInput label="Frequência máxima" unit="Hz" :min="10" :max="96000" :model-value="settings.maxHz" data-spectrogram-max @update:model-value="panel.setSpectrogram({ maxHz: number($event, DEFAULT_SPECTROGRAM.maxHz) })" />
      <AppSelect label="Janela" :model-value="settings.window" :options="WINDOW_OPTIONS" data-spectrogram-window @update:model-value="panel.setSpectrogram({ window: $event })" />
      <AppSelect label="Tamanho da janela" :model-value="String(settings.windowSize)" :options="sizeOptions" data-spectrogram-size @update:model-value="panel.setSpectrogram({ windowSize: Number($event) })" />
      <AppNumberInput label="Ganho" unit="dB" :min="-100" :max="100" :model-value="settings.gainDb" data-spectrogram-gain @update:model-value="panel.setSpectrogram({ gainDb: number($event, DEFAULT_SPECTROGRAM.gainDb) })" />
      <AppNumberInput label="Alcance" unit="dB" :min="1" :max="200" :model-value="settings.rangeDb" data-spectrogram-range @update:model-value="panel.setSpectrogram({ rangeDb: number($event, DEFAULT_SPECTROGRAM.rangeDb) })" />
      <AppButton size="sm" variant="ghost" data-spectrogram-reset @click="panel.setSpectrogram({ ...DEFAULT_SPECTROGRAM })">Restaurar o padrão</AppButton>
    </div>
  </div>
</template>

<style scoped>
.settings {
  position: absolute;
  top: var(--space-1);
  right: var(--space-1);
  z-index: 3;
}

.settings__panel {
  position: absolute;
  top: calc(100% + var(--space-1));
  right: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(8.5rem, 1fr));
  gap: var(--space-2);
  width: 20rem;
  max-width: calc(100vw - 2rem);
  padding: var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: 0 8px 24px rgb(0 0 0 / 0.35);
}

.settings__panel > :last-child {
  grid-column: 1 / -1;
}
</style>

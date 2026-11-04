<script setup lang="ts">
/* O painel Áudio: o editor de onda de um item da linha do tempo. Abre no lugar da linha do tempo (o "Voltar à linha do
   tempo" traz ela de volta) e junta a onda por zoom, as ferramentas de seleção, envelope, desenho e zoom, a reprodução
   (tocar, loop, scrub, velocidade, prévia do corte, medidor), os comandos de edição e a janela de efeito. Os atalhos do
   Audacity valem quando o foco está nele. Selecionar e dar zoom não mudam a spec; cada comando é um passo do desfazer. */
import { computed, ref } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import { useShortcutHandler } from '@/composables/useEditorShortcuts'
import { useWaveData } from '@/composables/useWaveData'
import { useWavePlayback } from '@/composables/useWavePlayback'
import { formatSpan, timeSample } from '@/lib/audioWave'
import type { AudioShortcutId } from '@/lib/keymap'
import { SPEEDS, useAudioPanelStore, type PanelTool } from '@/stores/audioPanel'
import { useEditorStore } from '@/stores/editor'
import { useKeymapStore } from '@/stores/keymap'
import AudioEffectDialog from './audio/AudioEffectDialog.vue'
import AudioMeter from './audio/AudioMeter.vue'
import AudioWaveView from './audio/AudioWaveView.vue'
import TransportIcon from './TransportIcon.vue'

const panel = useAudioPanelStore()
const editor = useEditorStore()
const keymap = useKeymapStore()

const waveWidth = ref(0)
const { data, error } = useWaveData(waveWidth)
const playback = useWavePlayback()
const effectOpen = ref(false)
const waveView = ref<InstanceType<typeof AudioWaveView> | null>(null)

const toolOptions: Array<{ value: PanelTool; label: string }> = [
  { value: 'select', label: 'Seleção' },
  { value: 'envelope', label: 'Envelope' },
  { value: 'draw', label: 'Desenho' },
  { value: 'zoom', label: 'Zoom' },
  { value: 'multi', label: 'Multi' },
]
const speedOptions = SPEEDS.map((speed) => ({ value: String(speed), label: `${String(speed).replace('.', ',')}x` }))

const wave = computed(() => panel.overview)
const building = computed(() => wave.value?.state === 'building')
const meta = computed(() => {
  const current = wave.value
  if (!current) return ''
  const channels = current.channels === 1 ? 'mono' : 'estéreo'
  return `${formatSpan(current.duration)} · ${(current.rate / 1000).toString().replace('.', ',')} kHz · ${channels}`
})

const selectionText = computed(() => {
  const selection = panel.selection
  if (!selection) return 'Sem seleção'
  const samples = timeSample(selection.end, panel.rate) - timeSample(selection.start, panel.rate)
  return `${formatSpan(selection.start)} a ${formatSpan(selection.end)} (${formatSpan(selection.end - selection.start)}, ${samples.toLocaleString('pt-BR')} amostras)`
})
const cursorText = computed(() => `${formatSpan(panel.position ?? panel.cursor)} · amostra ${timeSample(panel.position ?? panel.cursor, panel.rate).toLocaleString('pt-BR')}`)

const hasSelection = computed(() => panel.selection !== null)

function hint(label: string, id: AudioShortcutId): string {
  const keys = keymap.labelFor(id)
  return keys ? `${label} (${keys})` : label
}

/* ---------- atalhos: valem com o foco dentro do painel ---------- */

const actions: Record<AudioShortcutId, () => void> = {
  audio_play: () => void playback.toggle(),
  audio_loop_play: () => {
    if (panel.playing) {
      playback.stop()
      return
    }
    panel.loop = true
    void playback.play()
  },
  audio_pause: () => playback.pause(),
  audio_stop: () => playback.stop(),
  audio_cut_preview: () => void playback.previewCut(),
  audio_label: () => void panel.label(),
  audio_silence: () => void panel.silence(),
  audio_split: () => void panel.split(),
  audio_cut: () => void panel.cut(),
  audio_undo: () => void editor.undo(),
  audio_redo: () => void editor.redo(),
  audio_select_all: () => panel.selectAll(),
  audio_select_next_marker: () => void panel.selectToMarker(1),
  audio_select_prev_marker: () => void panel.selectToMarker(-1),
  audio_zoom_in: () => panel.zoomIn(),
  audio_zoom_out: () => panel.zoomOut(),
  audio_fit_selection: () => panel.zoomToSelection(),
  audio_fit_project: () => panel.zoomToProject(),
  audio_tool_select: () => panel.setTool('select'),
  audio_tool_envelope: () => panel.setTool('envelope'),
  audio_tool_draw: () => panel.setTool('draw'),
  audio_tool_zoom: () => panel.setTool('zoom'),
  audio_tool_multi: () => panel.setTool('multi'),
}
for (const [id, run] of Object.entries(actions) as Array<[AudioShortcutId, () => void]>) useShortcutHandler(id, run)

function focusWave(): void {
  waveView.value?.focus()
}

function openEffect(): void {
  playback.stop()
  effectOpen.value = true
}

function onSpeed(value: string): void {
  panel.setSpeed(Number(value))
}
</script>

<template>
  <section class="audio" tabindex="-1" data-audio-panel aria-label="Painel Áudio" @mousedown.self="focusWave">
    <header class="audio__head">
      <AppButton size="sm" variant="ghost" data-audio-back title="Fecha o editor de onda e volta à linha do tempo" @click="panel.close()">
        <AppIcon name="arrow-left" :size="16" />
        Voltar à linha do tempo
      </AppButton>
      <div class="audio__title">
        <strong data-audio-title>{{ panel.title }}</strong>
        <span class="audio__meta">{{ meta }}</span>
      </div>
      <span v-if="building" class="audio__build" role="status" data-audio-building>
        {{ wave?.stage || 'Preparando a onda' }}: {{ wave?.percent ?? 0 }}%
        <progress class="audio__progress" max="100" :value="wave?.percent ?? 0" />
      </span>
    </header>

    <div class="audio__bar" role="toolbar" aria-label="Ferramentas e edição">
      <SegmentedControl :model-value="panel.tool" label="Ferramenta" :options="toolOptions" data-audio-tools @update:model-value="panel.setTool($event)" />
      <span class="audio__group" role="group" aria-label="Zoom">
        <AppButton size="sm" :title="hint('Aproximar', 'audio_zoom_in')" aria-label="Aproximar" data-audio-zoom-in @click="panel.zoomIn()">+</AppButton>
        <AppButton size="sm" :title="hint('Afastar', 'audio_zoom_out')" aria-label="Afastar" data-audio-zoom-out @click="panel.zoomOut()">−</AppButton>
        <AppButton size="sm" :disabled="!hasSelection" :title="hint('Ajustar à seleção', 'audio_fit_selection')" data-audio-fit-selection @click="panel.zoomToSelection()">Seleção</AppButton>
        <AppButton size="sm" :title="hint('Ajustar ao áudio inteiro', 'audio_fit_project')" data-audio-fit-project @click="panel.zoomToProject()">Tudo</AppButton>
      </span>
      <span class="audio__group" role="group" aria-label="Edição">
        <AppButton size="sm" :disabled="!hasSelection || panel.busy" :title="hint('Silenciar a seleção', 'audio_silence')" data-audio-silence @click="panel.silence()">Silenciar</AppButton>
        <AppButton size="sm" :disabled="!hasSelection || panel.busy" :title="hint('Cortar a seleção', 'audio_cut')" data-audio-cut @click="panel.cut()">Cortar</AppButton>
        <AppButton size="sm" :disabled="!panel.canSplit || panel.busy" :title="hint('Dividir no cursor (só a voz gravada)', 'audio_split')" data-audio-split @click="panel.split()">Dividir</AppButton>
        <AppButton size="sm" :disabled="panel.busy" :title="hint('Marcador na seleção', 'audio_label')" data-audio-label @click="panel.label()">Marcador</AppButton>
        <AppButton size="sm" variant="primary" :disabled="!panel.ready || panel.busy" data-audio-effect @click="openEffect">Efeito...</AppButton>
      </span>
    </div>

    <div class="audio__bar" role="toolbar" aria-label="Reprodução">
      <span class="audio__group" role="group" aria-label="Transporte">
        <AppButton size="sm" icon-only aria-label="Ir ao começo" title="Ir ao começo" @click="panel.setCursor(0)"><TransportIcon name="start" :size="16" /></AppButton>
        <AppButton
          size="sm"
          icon-only
          :aria-label="panel.playing ? 'Parar' : 'Tocar'"
          :title="hint(panel.playing ? 'Parar' : 'Tocar a seleção, ou do cursor ao fim', 'audio_play')"
          data-audio-play
          @click="playback.toggle()"
        >
          <TransportIcon :name="panel.playing ? 'stop' : 'play'" :size="16" />
        </AppButton>
        <AppButton size="sm" icon-only :title="hint('Pausar', 'audio_pause')" aria-label="Pausar" :disabled="!panel.playing" data-audio-pause @click="playback.pause()"><TransportIcon name="pause" :size="16" /></AppButton>
        <AppButton size="sm" icon-only aria-label="Ir ao fim" title="Ir ao fim" @click="panel.setCursor(panel.duration)"><TransportIcon name="end" :size="16" /></AppButton>
      </span>
      <AppCheckbox v-model="panel.loop" label="Loop" data-audio-loop />
      <AppButton size="sm" :disabled="!hasSelection" :title="hint('Toca 2 s antes e 2 s depois da seleção, pulando-a', 'audio_cut_preview')" data-audio-cut-preview @click="playback.previewCut()">
        Prévia do corte
      </AppButton>
      <AppSelect label="Velocidade" hide-label :model-value="String(panel.speed)" :options="speedOptions" data-audio-speed @update:model-value="onSpeed" />
      <AudioMeter :levels="playback.levels.value" />
    </div>

    <p v-if="error" class="audio__error" role="alert" data-audio-error>{{ error }}</p>
    <ul v-if="wave?.notes?.length" class="audio__notes">
      <li v-for="note in wave.notes" :key="note">{{ note }}</li>
    </ul>

    <AudioWaveView
      ref="waveView"
      :data="data"
      @size="waveWidth = $event"
      @scrub="playback.scrub($event)"
      @scrub-end="playback.endScrub()"
    />

    <footer class="audio__foot">
      <span data-audio-selection>{{ selectionText }}</span>
      <span data-audio-cursor>Cursor: {{ cursorText }}</span>
    </footer>

    <AudioEffectDialog v-model:open="effectOpen" @preview-start="playback.stop()" />
  </section>
</template>

<style scoped>
.audio {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-xs);
  background: var(--color-bg-soft);
  outline: none;
}

.audio__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.audio__title {
  display: flex;
  flex: 1 1 10rem;
  align-items: baseline;
  gap: var(--space-3);
  min-width: 0;
  overflow: hidden;
  font-size: var(--text-sm);
  white-space: nowrap;
}

.audio__title strong {
  overflow: hidden;
  text-overflow: ellipsis;
}

.audio__meta {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.audio__build {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-warning);
  font-size: var(--text-xs);
}

.audio__progress {
  width: 7rem;
  height: 0.5rem;
}

.audio__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-3);
}

.audio__group {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
}

.audio__error {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-error-bg);
  color: var(--color-error);
  font-size: var(--text-sm);
}

.audio__notes {
  margin: 0;
  padding: 0 0 0 var(--space-4);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.audio__foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-2) var(--space-4);
  color: var(--color-text-soft);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}
</style>

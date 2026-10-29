<script setup lang="ts">
/* O transporte do player: ir ao início e ao fim, andar quadro a quadro, tocar e pausar, voltar (J), parar (K) e
   avançar (L) com velocidade que dobra, o timecode HH:MM:SS:QQ e o volume. Só chama o store do player; o relógio é dele. */
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppSlider from '@/components/ui/AppSlider.vue'
import { formatTimecode } from '@/lib/player'
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'
import TransportIcon from './TransportIcon.vue'

const editor = useEditorStore()
const player = usePlayerStore()

const fps = computed(() => editor.view?.fps || 30)
const timecode = computed(() => formatTimecode(editor.playhead, fps.value))
const duration = computed(() => formatTimecode(editor.total, fps.value))
const ready = computed(() => !!editor.view && editor.total > 0)

const volume = computed({
  get: () => player.volume,
  set: (value: number) => player.setVolume(value),
})

function volumeText(value: number): string {
  return `${Math.round(value * 100)}%`
}
</script>

<template>
  <div class="transport" role="group" aria-label="Transporte do player">
    <div class="transport__buttons">
      <AppButton size="sm" variant="ghost" icon-only aria-label="Ir ao início" title="Ir ao início" :disabled="!ready" @click="player.goStart()">
        <TransportIcon name="start" />
      </AppButton>
      <AppButton size="sm" variant="ghost" icon-only aria-label="Quadro anterior" title="Quadro anterior" :disabled="!ready" @click="player.stepFrame(-1)">
        <TransportIcon name="step-back" />
      </AppButton>
      <AppButton
        size="sm"
        variant="primary"
        icon-only
        :aria-label="player.playing ? 'Pausar' : 'Tocar'"
        :title="player.playing ? 'Pausar' : 'Tocar'"
        :disabled="!ready"
        @click="player.toggle()"
      >
        <TransportIcon :name="player.playing ? 'pause' : 'play'" />
      </AppButton>
      <AppButton size="sm" variant="ghost" icon-only aria-label="Próximo quadro" title="Próximo quadro" :disabled="!ready" @click="player.stepFrame(1)">
        <TransportIcon name="step-forward" />
      </AppButton>
      <AppButton size="sm" variant="ghost" icon-only aria-label="Ir ao fim" title="Ir ao fim" :disabled="!ready" @click="player.goEnd()">
        <TransportIcon name="end" />
      </AppButton>
    </div>

    <div class="transport__shuttle" role="group" aria-label="Velocidade">
      <AppButton size="sm" variant="ghost" icon-only aria-label="Voltar (J)" title="Voltar (J): repetir dobra a velocidade" :disabled="!ready" @click="player.bump(-1)">
        <TransportIcon name="rewind" />
      </AppButton>
      <AppButton size="sm" variant="ghost" icon-only aria-label="Parar (K)" title="Parar (K)" :disabled="!ready" @click="player.pause()">
        <TransportIcon name="stop" />
      </AppButton>
      <AppButton size="sm" variant="ghost" icon-only aria-label="Avançar (L)" title="Avançar (L): repetir dobra a velocidade" :disabled="!ready" @click="player.bump(1)">
        <TransportIcon name="forward" />
      </AppButton>
      <span class="transport__speed" aria-live="polite">{{ player.label }}</span>
    </div>

    <p class="transport__time" aria-label="Posição na linha do tempo">
      <span class="transport__timecode">{{ timecode }}</span>
      <span class="transport__total">/ {{ duration }}</span>
    </p>

    <div class="transport__volume">
      <TransportIcon name="volume" />
      <AppSlider v-model="volume" label="Volume" hide-label :min="0" :max="1" :step="0.05" :format="volumeText" />
    </div>
  </div>
</template>

<style scoped>
.transport {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-4);
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--color-border);
}

.transport__buttons,
.transport__shuttle {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.transport__speed {
  min-width: 3.5rem;
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}

.transport__time {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.transport__timecode {
  font-size: var(--text-md);
  color: var(--color-text);
}

.transport__total {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.transport__volume {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 10rem;
  flex: 1;
  color: var(--color-text-soft);
}

.transport__volume :deep(.slider) {
  flex: 1;
}
</style>

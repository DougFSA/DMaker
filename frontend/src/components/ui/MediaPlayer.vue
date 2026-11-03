<script setup lang="ts">
/* Player de áudio ou vídeo com o título e uma linha de dados (duração, tamanho) acima. Usa os controles nativos
   do navegador; `play`, `pause` e `seek` ficam expostos para o AbCompare e as telas conduzirem a reprodução. */
import { computed, ref } from 'vue'
import { bustCache } from '@/lib/files'

const props = defineProps<{
  src: string
  kind: 'audio' | 'video'
  title?: string
  /** Dados curtos mostrados sob o título, separados por ponto médio: ["12,3 s", "1,2 MB"]. */
  meta?: string[]
  /** Muda quando o servidor regravou o arquivo no mesmo endereço, para o navegador buscar de novo. */
  refreshKey?: string | number
  autoplay?: boolean
}>()

const emit = defineEmits<{
  play: []
  pause: []
  ended: []
  timeupdate: [seconds: number]
  loadedmetadata: [duration: number]
}>()

const element = ref<HTMLMediaElement | null>(null)
const url = computed(() => (props.refreshKey === undefined ? props.src : bustCache(props.src, props.refreshKey)))
const caption = computed(() => (props.meta ?? []).filter(Boolean).join(' · '))

/** Toca; o navegador pode recusar (política de autoplay), então a promessa rejeita nesse caso. */
async function play(): Promise<void> {
  await element.value?.play()
}

function pause(): void {
  element.value?.pause()
}

function seek(seconds: number): void {
  if (element.value) element.value.currentTime = Math.max(0, seconds)
}

defineExpose({
  play,
  pause,
  seek,
  /** Posição atual, em segundos. */
  currentTime: () => element.value?.currentTime ?? 0,
  element,
})
</script>

<template>
  <figure class="player">
    <figcaption v-if="title || caption || $slots.actions" class="player__caption">
      <div class="player__text">
        <strong v-if="title" class="player__title">{{ title }}</strong>
        <span v-if="caption" class="player__meta">{{ caption }}</span>
      </div>
      <div v-if="$slots.actions" class="player__actions"><slot name="actions" /></div>
    </figcaption>
    <video
      v-if="kind === 'video'"
      ref="element"
      class="player__media player__media--video"
      :src="url"
      :aria-label="title"
      controls
      playsinline
      preload="metadata"
      :autoplay="autoplay"
      @play="emit('play')"
      @pause="emit('pause')"
      @ended="emit('ended')"
      @timeupdate="emit('timeupdate', ($event.target as HTMLMediaElement).currentTime)"
      @loadedmetadata="emit('loadedmetadata', ($event.target as HTMLMediaElement).duration)"
    >
      Seu navegador não consegue tocar este vídeo.
    </video>
    <audio
      v-else
      ref="element"
      class="player__media"
      :src="url"
      :aria-label="title"
      controls
      preload="metadata"
      :autoplay="autoplay"
      @play="emit('play')"
      @pause="emit('pause')"
      @ended="emit('ended')"
      @timeupdate="emit('timeupdate', ($event.target as HTMLMediaElement).currentTime)"
      @loadedmetadata="emit('loadedmetadata', ($event.target as HTMLMediaElement).duration)"
    >
      Seu navegador não consegue tocar este áudio.
    </audio>
  </figure>
</template>

<style scoped>
.player {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
  margin: 0;
}

.player__caption {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-4);
}

.player__text {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-1) var(--space-3);
  min-width: 0;
}

.player__title {
  font-size: var(--text-sm);
  font-weight: 600;
}

.player__meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.player__actions {
  display: flex;
  gap: var(--space-2);
}

.player__media {
  width: 100%;
  min-width: 0;
}

.player__media--video {
  max-height: 22rem;
  border-radius: var(--radius-sm);
  background: #000;
}
</style>

<script setup lang="ts">
/* Comparação A/B de dois áudios ou vídeos (original e corrigido, original e dublado): dois players em que tocar
   um pausa o outro. Os botões "Ouvir" tocam o lado escolhido do ponto certo: da folga em volta da região trocada,
   do ponto em que o outro estava, ou do começo. */
import { computed, ref } from 'vue'
import { AB_PADDING_S, abWindow, type AbRange } from '@/lib/ab'
import AppButton from './AppButton.vue'
import DownloadButton from './DownloadButton.vue'
import MediaPlayer from './MediaPlayer.vue'

export interface AbSide {
  /** Nome do lado ("Original", "Corrigido"): vira o título do player e o texto do botão. */
  label: string
  src: string
  meta?: string[]
  refreshKey?: string | number
  /** Endereço para baixar este lado; sem ele, o lado não tem botão de baixar. */
  downloadUrl?: string
  downloadName?: string
}

const props = withDefaults(
  defineProps<{
    first: AbSide
    second: AbSide
    kind: 'audio' | 'video'
    /** Início e fim, em segundos, do trecho trocado: o "Ouvir" toca só ele, com folga, e para no fim da janela. */
    region?: readonly [number, number] | null
    /** Sem região, de onde o "Ouvir" parte: do ponto em que o outro lado estava ou do começo. */
    startAt?: 'other' | 'beginning'
    /** Nome do grupo para leitor de tela. */
    label?: string
  }>(),
  { region: null, startAt: 'other', label: 'Comparar antes e depois' },
)

type Side = 'first' | 'second'
type PlayerHandle = InstanceType<typeof MediaPlayer>

const players = { first: ref<PlayerHandle | null>(null), second: ref<PlayerHandle | null>(null) }
const playing = ref<Side | null>(null)
const notice = ref('')
// o lado que o botão "Ouvir" iniciou e onde ele deve parar (só com região)
let stopAt: { side: Side; end: number } | null = null

const other = (side: Side): Side => (side === 'first' ? 'second' : 'first')
const windowOf = computed<AbRange | null>(() => (props.region ? abWindow(props.region) : null))
const padding = String(AB_PADDING_S).replace('.', ',')

/** Tocar um lado, por qualquer meio (botão ou controle nativo), pausa o outro. */
function onPlay(side: Side): void {
  playing.value = side
  notice.value = ''
  players[other(side)].value?.pause()
}

function onPause(side: Side): void {
  if (playing.value === side) playing.value = null
  // pausar à mão encerra a janela: retomar depois toca normalmente
  if (stopAt?.side === side) stopAt = null
}

function onTimeUpdate(side: Side, seconds: number): void {
  if (stopAt?.side === side && seconds >= stopAt.end) {
    stopAt = null
    players[side].value?.pause()
  }
}

async function listen(side: Side): Promise<void> {
  const target = players[side].value
  if (!target) return
  const range = windowOf.value
  const position = props.startAt === 'other' ? (players[other(side)].value?.currentTime() ?? 0) : 0
  players[other(side)].value?.pause()
  stopAt = range ? { side, end: range.end } : null
  target.seek(range ? range.start : position)
  try {
    await target.play()
  } catch {
    stopAt = null
    notice.value = 'O navegador bloqueou a reprodução. Use o player para ouvir.'
  }
}

const sides = computed(() => [
  { key: 'first' as const, data: props.first },
  { key: 'second' as const, data: props.second },
])
</script>

<template>
  <section class="ab" role="group" :aria-label="label">
    <div class="ab__sides">
      <div v-for="side in sides" :key="side.key" :class="['ab__side', { 'is-playing': playing === side.key }]">
        <MediaPlayer
          :ref="(instance) => (players[side.key].value = instance as PlayerHandle | null)"
          :src="side.data.src"
          :kind="kind"
          :title="side.data.label"
          :meta="side.data.meta"
          :refresh-key="side.data.refreshKey"
          @play="onPlay(side.key)"
          @pause="onPause(side.key)"
          @timeupdate="onTimeUpdate(side.key, $event)"
        >
          <template v-if="side.data.downloadUrl" #actions>
            <DownloadButton size="sm" :url="side.data.downloadUrl" :filename="side.data.downloadName" />
          </template>
        </MediaPlayer>
        <AppButton size="sm" class="ab__listen" @click="listen(side.key)">
          Ouvir {{ side.data.label.toLowerCase() }}
        </AppButton>
      </div>
    </div>
    <p v-if="windowOf" class="ab__hint">
      Ouvir toca o trecho trocado com {{ padding }} s antes e depois, para você ouvir a emenda.
    </p>
    <p v-if="notice" class="ab__notice" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.ab {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ab__sides {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
  gap: var(--space-4);
}

.ab__side {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  transition: border-color var(--transition);
}

.ab__side.is-playing {
  border-color: var(--color-accent);
}

.ab__listen {
  align-self: flex-start;
}

.ab__hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.ab__notice {
  font-size: var(--text-sm);
  color: var(--color-warning);
}
</style>

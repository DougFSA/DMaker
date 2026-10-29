<script setup lang="ts">
/* O painel Player do editor: o palco, o transporte e o som. O som é UM `<audio>` preso ao relógio tocando a
   mixagem que o servidor faz com o mesmo grafo de áudio do render; todo `<video>` do palco fica mudo. Enquanto a
   mixagem não está pronta (projeto recém-aberto ou recém-editado), o som sai ao vivo, por trilha, com o aviso
   "áudio aproximado". */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { PlayerAudio } from '@/lib/playerEngine'
import { liveAudioPlan, type LivePlan } from '@/lib/playerAudio'
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'
import { usePlayerMediaStore } from '@/stores/playerMedia'
import PlayerStage from './PlayerStage.vue'
import PlayerTransport from './PlayerTransport.vue'

const editor = useEditorStore()
const player = usePlayerStore()
const media = usePlayerMediaStore()

const audioHost = ref<HTMLElement | null>(null)
const soundBlocked = ref(false)
let audio: PlayerAudio | null = null

const EMPTY_PLAN: LivePlan = { channels: [], dropped: [] }

const hasView = computed(() => !!editor.view && !!editor.spec)

/** O que dizer no lugar do palco enquanto não há linha do tempo: calculando, ou o motivo de não ter (spec inválida). */
const emptyTitle = computed(() => (editor.viewError ? 'A prévia não abriu' : editor.viewBusy ? 'Calculando a prévia' : 'Sem prévia ainda'))
const emptyDescription = computed(() =>
  editor.viewError || 'O player aparece quando a linha do tempo do projeto estiver calculada.',
)

/** O estado do som em palavras, para o aviso e para quem inspeciona a tela. */
const soundState = computed<'mix' | 'live'>(() => (media.current ? 'mix' : 'live'))

const mixProgress = computed(() => {
  if (media.mixState === 'building') {
    return media.mixLabel ? `${media.mixLabel}${media.mixPercent > 0 ? ` (${media.mixPercent}%)` : ''}` : 'preparando a mixagem'
  }
  if (media.mixState === 'failed') return `a mixagem falhou: ${media.mixError}`
  return 'preparando a mixagem'
})

const proxyStatus = computed(() => {
  const total = media.proxies.filter((entry) => !entry.missing).length
  return total > 0 && media.proxiesPending > 0 ? `Proxies leves: ${media.proxiesReady}/${total} prontos` : ''
})

function syncAudio(): void {
  if (!audio) return
  audio.setMix(media.mixUrl)
  const view = editor.view
  const spec = editor.spec
  const plan =
    !media.current && view && spec
      ? liveAudioPlan(editor.playhead, { view, spec, proxyUrls: media.proxyUrls, master: player.volume })
      : EMPTY_PLAN
  audio.update({
    time: editor.playhead,
    rate: player.rate,
    volume: player.volume,
    mixCurrent: media.current,
    plan,
    now: performance.now(),
  })
}

watch(
  [
    () => editor.playhead,
    () => player.rate,
    () => player.volume,
    () => media.current,
    () => media.mixUrl,
    () => editor.view,
    () => media.proxyUrls,
  ],
  syncAudio,
  { flush: 'post' },
)

watch(
  () => player.playing,
  (playing) => {
    if (playing) soundBlocked.value = false
    else audio?.pause()
  },
)

/** J, K e L no teclado, como numa ilha de edição: voltar, parar e avançar (repetir dobra a velocidade). Fora de
 * campos de texto, e sem Ctrl/Alt/Cmd, que são dos atalhos do navegador e do editor. */
function onKeydown(event: KeyboardEvent): void {
  if (event.ctrlKey || event.metaKey || event.altKey || editor.status !== 'ready') return
  const target = event.target
  if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return
  const key = event.key.toLowerCase()
  if (key === 'j') player.bump(-1)
  else if (key === 'k') player.pause()
  else if (key === 'l') player.bump(1)
  else return
  event.preventDefault()
}

onMounted(() => {
  audio = new PlayerAudio(
    () => document.createElement('audio'),
    () => {
      soundBlocked.value = true
      player.pause()
    },
    (path) => media.onMediaError(path),
    audioHost.value,
  )
  media.start()
  window.addEventListener('keydown', onKeydown)
  syncAudio()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  player.pause()
  audio?.dispose()
  audio = null
  media.stop()
})
</script>

<template>
  <AppCard class="player" title="Player" flush :data-sound="soundState">
    <template #actions>
      <AppBadge v-if="hasView" :tone="media.current ? 'accent' : 'warning'" dot>
        {{ media.current ? 'Áudio da mixagem' : 'Áudio aproximado' }}
      </AppBadge>
    </template>

    <EmptyState v-if="!hasView" icon="video" :title="emptyTitle" :description="emptyDescription" />

    <template v-else>
      <PlayerStage />
      <PlayerTransport />

      <div class="player__notes">
        <p v-if="!media.current" class="note note--warning" role="status">
          <AppIcon name="info" :size="16" />
          <span>Áudio aproximado: {{ mixProgress }}. A mixagem fica pronta e passa a soar como o vídeo final.</span>
        </p>
        <p v-for="warning in media.mixWarnings" :key="warning" class="note note--info">
          <AppIcon name="info" :size="16" />
          <span>{{ warning }}</span>
        </p>
        <p v-for="warning in editor.view?.warnings ?? []" :key="warning" class="note note--warning" role="status">
          <AppIcon name="alert" :size="16" />
          <span>{{ warning }}</span>
        </p>
        <p v-if="soundBlocked" class="note note--warning" role="alert">
          <AppIcon name="alert" :size="16" />
          <span>O navegador bloqueou o som. Clique em Tocar para liberar.</span>
        </p>
        <p v-if="proxyStatus || media.proxyNotice" class="note note--info">
          <AppIcon name="film" :size="16" />
          <span>{{ media.proxyNotice || proxyStatus }}</span>
          <AppButton
            v-if="media.proxiesPending > 0 && !media.proxyBuilding"
            size="sm"
            variant="ghost"
            @click="media.buildProxies()"
          >
            Gerar proxies
          </AppButton>
        </p>
        <p class="note note--muted">Prévia aproximada: transições, legendas e efeitos só aparecem no render.</p>
      </div>
    </template>

    <div ref="audioHost" class="player__pool" hidden aria-hidden="true" />
  </AppCard>
</template>

<style scoped>
.player__notes {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3) var(--space-3);
}

.note {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-size: var(--text-xs);
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.note--warning {
  color: var(--color-warning);
}

.note--info {
  color: var(--color-info);
}

.note--muted {
  color: var(--color-text-muted);
}

.player__pool {
  width: 0;
  height: 0;
  overflow: hidden;
}
</style>

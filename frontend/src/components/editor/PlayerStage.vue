<script setup lang="ts">
/* O palco do player: o quadro na proporção do formato com as camadas na ordem do render (trecho da V1, imagens e
   barra de progresso, vídeos sobrepostos, texto). Todo `<video>` daqui é mudo: o som é de um `<audio>` só, preso ao
   mesmo relógio (ver `PlayerPanel`). Trecho ou sobreposição de arquivo ausente aparece marcado "fonte não encontrada". */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { syncVideo } from '@/lib/playerEngine'
import { stageLayers, type PipLayer, type StageLayers } from '@/lib/playerStage'
import { baseName } from '@/lib/format'
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'
import { usePlayerMediaStore } from '@/stores/playerMedia'

const editor = useEditorStore()
const player = usePlayerStore()
const media = usePlayerMediaStore()

const stage = ref<HTMLElement | null>(null)
const videos = new Map<string, HTMLVideoElement>()
// endereços que o navegador não conseguiu abrir (HEVC, por exemplo): enquanto o proxy não chega, não adianta tocar
const failed = ref(new Set<string>())

const layers = computed<StageLayers | null>(() => {
  const view = editor.view
  const spec = editor.spec
  if (!view || !spec) return null
  return stageLayers(editor.playhead, { view, spec, theme: media.theme, proxyUrls: media.proxyUrls })
})

const ratio = computed(() => {
  const view = editor.view
  return view && view.width > 0 && view.height > 0 ? view.width / view.height : 9 / 16
})

/** Os vídeos do trecho da V1: o de agora e o do próximo corte, já carregado para o corte não piscar. */
const v1Videos = computed(() => {
  const v1 = layers.value?.v1
  if (!v1 || v1.kind !== 'clip' || v1.missing) return []
  const entries: Array<{ url: string; current: boolean }> = []
  if (v1.url) entries.push({ url: v1.url, current: true })
  if (v1.nextUrl && v1.nextUrl !== v1.url) entries.push({ url: v1.nextUrl, current: false })
  return entries
})

function bindVideo(key: string, element: unknown): void {
  if (element instanceof HTMLVideoElement) videos.set(key, element)
  else videos.delete(key)
}

function onVideoError(path: string | null, url: string | null): void {
  if (url) failed.value = new Set(failed.value).add(url)
  if (path) media.onMediaError(path)
}

function syncVideos(): void {
  const current = layers.value
  if (!current) return
  const { v1 } = current
  if (v1.kind === 'clip' && v1.url) {
    const element = videos.get(`v1:${v1.url}`)
    if (element) syncVideo(element, { fileTime: v1.fileTime, speed: v1.speed, rate: player.rate, errored: failed.value.has(v1.url) })
  }
  for (const pip of current.pips) {
    if (!pip.url) continue
    const element = videos.get(`pip:${pip.id}`)
    if (element) syncVideo(element, { fileTime: pip.fileTime, speed: 1, rate: player.rate, errored: failed.value.has(pip.url) })
  }
  // o vídeo do próximo corte só carrega: não toca
  for (const entry of v1Videos.value) {
    const element = videos.get(`v1:${entry.url}`)
    if (element && !entry.current && !element.paused) element.pause()
  }
}

// a cada quadro (o cursor anda) e a cada mudança de velocidade, cada vídeo volta a ficar preso ao relógio
watch([layers, () => player.rate], syncVideos, { flush: 'post' })

// o tamanho do texto acompanha a altura do palco, como no render (que mede em 1080 de lado menor)
let observer: ResizeObserver | null = null
function measure(): void {
  const element = stage.value
  if (!element) return
  element.style.setProperty('--stage-h', `${element.clientHeight}px`)
}
onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && stage.value) {
    observer = new ResizeObserver(measure)
    observer.observe(stage.value)
  }
})
onBeforeUnmount(() => observer?.disconnect())

function pipKey(pip: PipLayer): string {
  return `pip:${pip.id}`
}
</script>

<template>
  <div class="stage-wrap">
    <div
      ref="stage"
      class="stage"
      role="img"
      :aria-label="`Palco do player, quadro de ${editor.view?.width ?? 0} por ${editor.view?.height ?? 0}`"
      :style="{ '--ratio': String(ratio) }"
    >
      <template v-if="layers">
        <div class="layer layer--v1">
          <video
            v-for="entry in v1Videos"
            v-show="entry.current"
            :key="entry.url"
            :ref="(element) => bindVideo(`v1:${entry.url}`, element)"
            class="media"
            :src="entry.url"
            :preload="entry.current ? 'auto' : 'metadata'"
            muted
            playsinline
            @error="onVideoError(layers.v1.path, entry.url)"
          />
          <img
            v-if="(layers.v1.kind === 'image' || layers.v1.kind === 'card') && layers.v1.url && !layers.v1.missing"
            :key="layers.v1.url"
            class="media"
            :src="layers.v1.url"
            alt=""
          />
          <p v-if="layers.v1.missing" class="missing" role="alert">
            <strong>Fonte não encontrada</strong>
            <span v-if="layers.v1.item?.path">{{ baseName(layers.v1.item.path) }}</span>
          </p>
        </div>

        <div class="layer layer--gr">
          <template v-for="gr in layers.gr" :key="gr.id">
            <div v-if="gr.kind === 'progress-bar'" class="progress" :style="gr.style">
              <div class="progress__fill" :style="{ width: `${(gr.fraction * 100).toFixed(2)}%` }" />
            </div>
            <img v-else class="overlay-image" :src="gr.url ?? undefined" :style="gr.style" alt="" />
          </template>
        </div>

        <div class="layer layer--pip">
          <div v-for="pip in layers.pips" :key="pip.id" :class="['pip', { 'pip--missing': pip.missing }]" :style="pip.style">
            <video
              v-if="pip.url && !pip.missing"
              :ref="(element) => bindVideo(pipKey(pip), element)"
              class="media"
              :src="pip.url"
              preload="auto"
              muted
              playsinline
              @error="onVideoError(pip.path, pip.url)"
            />
            <span v-else-if="pip.missing" class="pip__label">Fonte não encontrada</span>
          </div>
        </div>

        <div class="layer layer--tx">
          <div v-for="text in layers.tx" :key="text.id" :class="['text', `text--${text.role}`]" :style="text.style">
            {{ text.text }}
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.stage-wrap {
  display: flex;
  justify-content: center;
  padding: var(--space-3);
  background: var(--color-bg-soft);
}

.stage {
  --stage-max-h: min(52vh, 34rem);
  position: relative;
  aspect-ratio: var(--ratio);
  width: min(100%, calc(var(--stage-max-h) * var(--ratio)));
  overflow: hidden;
  background: #000;
  border-radius: var(--radius-sm);
}

.layer {
  position: absolute;
  inset: 0;
}

.layer--gr,
.layer--pip,
.layer--tx {
  pointer-events: none;
}

.media {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.missing {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-3);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-warning);
  background: repeating-linear-gradient(135deg, rgb(242 193 78 / 0.12) 0 10px, transparent 10px 20px);
  overflow-wrap: anywhere;
}

.overlay-image {
  position: absolute;
  display: block;
}

.progress {
  position: absolute;
  left: 0;
  right: 0;
  background: rgb(255 255 255 / 0.2);
}

.progress__fill {
  height: 100%;
  background: var(--color-accent);
}

.pip {
  position: absolute;
  overflow: hidden;
  aspect-ratio: 16 / 9;
  background: #000;
}

.pip--missing {
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--color-warning);
}

.pip__label {
  padding: var(--space-1);
  font-size: var(--text-xs);
  text-align: center;
  color: var(--color-warning);
}

.text {
  position: absolute;
  left: 6%;
  right: 6%;
  text-align: center;
  font-weight: 600;
  line-height: 1.15;
  text-shadow: 0 2px 6px rgb(0 0 0 / 0.6);
}
</style>

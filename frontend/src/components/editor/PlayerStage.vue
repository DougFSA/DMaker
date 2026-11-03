<script setup lang="ts">
/* O palco do player: o quadro na proporção do formato com as camadas na ordem do render (trecho da V1, imagens e
   barra de progresso, vídeos sobrepostos, texto). Todo `<video>` daqui é mudo: o som é de um `<audio>` só, preso ao
   mesmo relógio (ver `PlayerPanel`). Trecho ou sobreposição de arquivo ausente aparece marcado "fonte não encontrada".
   Texto, imagem e PiP ficam nas caixas que o servidor calcula; por cima vão a zona segura (se ligada) e uma caixa
   clicável por sobreposição ativa, que a escolhe no inspetor. Os gestos de arrastar e redimensionar entram nesta
   camada de caixas. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { boxRectStyle, safeZoneStyles, sidesText, stageBoxes, type StageBox } from '@/lib/overlayBoxes'
import { syncVideo } from '@/lib/playerEngine'
import { stageLayers, type PipLayer, type StageLayers } from '@/lib/playerStage'
import { baseName } from '@/lib/format'
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'
import { usePlayerMediaStore } from '@/stores/playerMedia'

const editor = useEditorStore()
const player = usePlayerStore()
const media = usePlayerMediaStore()

/** Do topo do quadro para baixo (fração), a caixa que começa antes disto leva o rótulo por dentro, senão ele sairia do palco. */
const LABEL_OUTSIDE_MIN_TOP = 0.05

const stage = ref<HTMLElement | null>(null)
const videos = new Map<string, HTMLVideoElement>()
// endereços que o navegador não conseguiu abrir (HEVC, por exemplo): enquanto o proxy não chega, não adianta tocar
const failed = ref(new Set<string>())

const layers = computed<StageLayers | null>(() => {
  const view = editor.view
  const spec = editor.spec
  if (!view || !spec) return null
  return stageLayers(editor.playhead, { view, spec, theme: media.theme, proxyUrls: media.proxyUrls, boxes: editor.boxes })
})

/** As caixas das sobreposições que estão na tela neste instante. */
const boxes = computed<StageBox[]>(() => stageBoxes(editor.playhead, editor.view, editor.boxes))

/** As margens da zona segura do formato, quando o botão do player a liga. */
const safeZone = computed(() => (player.safeZoneShown && editor.boxes ? safeZoneStyles(editor.boxes.safe_zone) : null))

function boxClasses(entry: StageBox): Array<string | Record<string, boolean>> {
  const { box } = entry
  return [
    'box',
    `box--${box.kind}`,
    {
      'box--selected': editor.selectedOverlay === box.index,
      'box--warn': box.outside_safe_zone.length > 0,
      'box--locked': !box.movable,
      // o rótulo fica acima da caixa para não cobrir o conteúdo; colada no topo do quadro, ele passa para dentro
      'box--label-in': box.top < LABEL_OUTSIDE_MIN_TOP,
    },
  ]
}

/** O nome acessível da caixa: o rótulo, o motivo de não se mover e os lados que invadem a zona segura. */
function boxName(entry: StageBox): string {
  const { box } = entry
  const parts = [entry.label]
  if (!box.movable && box.locked_reason) parts.push(box.locked_reason)
  if (box.outside_safe_zone.length > 0) parts.push(`fora da zona segura ${sidesText(box.outside_safe_zone)}`)
  return parts.join(', ')
}

function chooseBox(entry: StageBox): void {
  editor.selectOverlay(entry.box.index, { reveal: true })
}

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
      role="group"
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

        <div v-if="safeZone" class="layer layer--safe" data-layer="safe-zone" aria-hidden="true">
          <div class="safe safe--band" :style="safeZone.top" />
          <div class="safe safe--band" :style="safeZone.bottom" />
          <div class="safe safe--band" :style="safeZone.left" />
          <div class="safe safe--band" :style="safeZone.right" />
          <div class="safe safe--edge" :style="safeZone.inside"><span class="safe__label">Zona segura</span></div>
        </div>

        <div class="layer layer--boxes" data-layer="boxes">
          <button
            v-for="entry in boxes"
            :key="entry.itemId"
            type="button"
            :class="boxClasses(entry)"
            :style="boxRectStyle(entry.box)"
            :data-overlay="entry.box.index"
            :aria-label="boxName(entry)"
            :aria-pressed="editor.selectedOverlay === entry.box.index"
            :title="entry.box.locked_reason ?? boxName(entry)"
            @click="chooseBox(entry)"
          >
            <span class="box__label">{{ entry.label }}</span>
          </button>
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
  /* o layout de tela dá a altura do encaixe; fora dele, a janela decide */
  --stage-max-h: var(--editor-stage-max-h, min(52vh, 34rem));
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
.layer--tx,
.layer--safe,
.layer--boxes {
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
  /* o libass põe cada linha numa célula de 1,76 do corpo da Poppins (veja `LIBASS_CELL_RATIO`) */
  line-height: 1.76;
  text-shadow: 0 2px 6px rgb(0 0 0 / 0.6);
}

/* a zona segura: o que o app da rede social cobre fica escurecido, e a área livre ganha um contorno tracejado */
.safe {
  position: absolute;
}

.safe--band {
  background: rgb(255 122 122 / 0.22);
}

.safe--edge {
  border: 1px dashed rgb(255 255 255 / 0.85);
}

.safe__label {
  position: absolute;
  right: 4px;
  bottom: 2px;
  font-size: 10px;
  line-height: 1;
  color: rgb(255 255 255 / 0.9);
  text-shadow: 0 1px 2px rgb(0 0 0 / 0.8);
}

/* a caixa de cada sobreposição: contorno por cima do vídeo, que só aceita o clique na própria caixa */
.box {
  position: absolute;
  padding: 0;
  border: 1px dashed rgb(255 255 255 / 0.9);
  border-radius: 2px;
  background: transparent;
  box-shadow: 0 0 0 1px rgb(0 0 0 / 0.5);
  color: #fff;
  cursor: pointer;
  pointer-events: auto;
}

.box:hover {
  background: rgb(255 255 255 / 0.1);
}

.box:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 1px;
}

.box--html {
  background: rgb(143 163 255 / 0.12);
}

.box--locked {
  border-style: dotted;
  cursor: default;
}

.box--warn {
  border-color: #f2c14e;
}

.box--selected {
  z-index: 1;
  border: 2px solid var(--color-accent);
}

.box--selected.box--warn {
  border-color: #f2c14e;
}

.box__label {
  position: absolute;
  left: -1px;
  bottom: calc(100% + 1px);
  padding: 1px 4px;
  font-size: 10px;
  line-height: 1.3;
  white-space: nowrap;
  background: rgb(0 0 0 / 0.65);
}

.box--label-in .box__label {
  top: 0;
  bottom: auto;
}

.box--selected .box__label {
  color: var(--color-on-accent);
  background: var(--color-accent);
}

.box--warn .box__label {
  color: #1b1300;
  background: #f2c14e;
}
</style>

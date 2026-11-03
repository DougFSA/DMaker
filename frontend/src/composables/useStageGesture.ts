/* Arrastar e redimensionar uma sobreposição no palco. O mouse é tratado no `document` (como a linha do tempo): o botão da
   caixa ou a alça só começam o gesto, e ele continua mesmo com o ponteiro fora do palco.

   Um clique sem movimento segue sendo só seleção. Depois de alguns pixels vira gesto: a caixa anda no cliente, sem
   chamar o servidor, e o aviso da zona segura é recalculado aqui (o `outside_safe_zone` do servidor fica velho). Ao
   soltar, na ordem: o fim do gesto, UMA mudança na spec (um passo do desfazer), a gravação, as caixas novas do
   servidor, o aviso da zona segura e o pedido do quadro real. */
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import type { Ref } from 'vue'
import type { SafeZoneSide } from '@/api'
import { boxLabel, sidesText, type PlacedBox } from '@/lib/overlayBoxes'
import {
  applyPatch,
  gesturePatch,
  moveStep,
  resizeStep,
  sidesOutside,
  snapSettings,
  type FrameSize,
  type GestureStep,
  type Guides,
  type Handle,
} from '@/lib/overlayGesture'
import { useCatalogStore } from '@/stores/catalog'
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'
import { useRealFrameStore } from '@/stores/realFrame'

/** Quanto o ponteiro precisa andar (px) antes de um clique virar gesto. */
export const STAGE_DRAG_THRESHOLD_PX = 3
/** Quanto esperar as caixas novas do servidor antes de largar a caixa do gesto mesmo assim (ms). */
export const SETTLE_TIMEOUT_MS = 3000

type Loose = Record<string, unknown>

/** A caixa como o gesto a deixa neste instante: o contorno, o texto, a imagem e o PiP do palco seguem esta. */
export interface LiveGesture {
  index: number
  mode: 'move' | 'resize'
  box: PlacedBox
  guides: Guides
}

interface Drag {
  id: number
  mode: 'move' | 'resize'
  handle: Handle | null
  /** A caixa de partida, como o servidor a calculou. */
  box: PlacedBox
  startX: number
  startY: number
  /** O tamanho do palco na tela (px) quando o gesto começou: a conta de pixel para fração. */
  stagePx: { width: number; height: number }
  /** O quadro nativo e a zona segura quando o gesto começou. */
  frame: FrameSize
  zone: { top: number; bottom: number; left: number; right: number }
  project: string
  began: boolean
}

export function useStageGesture(stage: Ref<HTMLElement | null>) {
  const editor = useEditorStore()
  const player = usePlayerStore()
  const catalog = useCatalogStore()
  const realFrame = useRealFrameStore()

  /** O gesto em andamento (ou recém-solto, até as caixas novas do servidor chegarem). */
  const live = shallowRef<LiveGesture | null>(null)
  /** Os avisos do último gesto: saiu da zona segura, deixou de seguir a região. */
  const notices = ref<string[]>([])

  let drag: Drag | null = null
  let serial = 0
  // depois de soltar um gesto o navegador ainda manda o `click` ao botão da caixa: ele não é uma escolha nova, e abrir o
  // inspetor nele faria a página pular para longe do palco a cada gesto
  let swallowClick = false
  let disposed = false
  // o texto da spec quando os avisos foram postos: qualquer outra mudança nela (desfazer, recarregar) os tira
  let noticeSpec: string | null = null

  function removeListeners(): void {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.removeEventListener('keydown', onKey)
  }

  function clearNotices(): void {
    notices.value = []
    noticeSpec = null
  }

  function stepFor(current: Drag, event: MouseEvent): GestureStep {
    const dx = (event.clientX - current.startX) / current.stagePx.width
    const dy = (event.clientY - current.startY) / current.stagePx.height
    // Alt desliga o ímã durante o gesto
    const snap = event.altKey ? null : snapSettings(current.zone, current.stagePx)
    return current.mode === 'move' || !current.handle
      ? moveStep(current.box, dx, dy, snap)
      : resizeStep(current.box, current.handle, dx, dy, snap, current.frame)
  }

  function onMove(event: MouseEvent): void {
    const current = drag
    if (!current) return
    if (!current.began) {
      if (Math.hypot(event.clientX - current.startX, event.clientY - current.startY) < STAGE_DRAG_THRESHOLD_PX) return
      current.began = true
      current.id = serial += 1
      // o gesto vale para o instante do cursor: com o player andando o cursor fugiria da caixa
      player.pause()
      editor.beginGesture()
      realFrame.invalidate()
      clearNotices()
      editor.selectOverlay(current.box.index)
    }
    const step = stepFor(current, event)
    live.value = {
      index: current.box.index,
      mode: current.mode,
      box: { ...step.box, outside_safe_zone: sidesOutside(step.box, current.zone, current.frame) },
      guides: step.guides,
    }
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return
    event.preventDefault()
    cancel()
  }

  function onUp(): void {
    const current = drag
    removeListeners()
    drag = null
    // sem movimento foi um clique: a seleção é do `click` do botão
    if (!current?.began) return
    swallowClick = true
    setTimeout(() => (swallowClick = false), 0)
    void commit(current)
  }

  /** O `click` que acompanha o fim de um gesto: quem trata o clique da caixa o ignora (devolve verdadeiro uma vez). */
  function consumeClick(): boolean {
    const swallowed = swallowClick
    swallowClick = false
    return swallowed
  }

  /** Larga o gesto sem gravar nada (Esc, ou o palco saindo da tela). */
  function cancel(): void {
    const current = drag
    removeListeners()
    drag = null
    if (current?.began) {
      editor.endGesture()
      live.value = null
    }
  }

  /** O botão da caixa (corpo, `handle` nulo) ou uma alça aperta o mouse: o gesto está pronto para começar. */
  function begin(event: MouseEvent, box: PlacedBox, handle: Handle | null): void {
    if (event.button !== 0 || !box.movable) return
    const element = stage.value
    const layout = editor.boxes
    if (!element || !layout || !editor.name) return
    const rect = element.getBoundingClientRect()
    // sem medida (a caixa ainda não foi desenhada) não há como traduzir pixel em fração
    if (rect.width <= 0 || rect.height <= 0) return
    cancel()
    // evita a seleção de texto da página e o arrasto nativo durante o gesto
    event.preventDefault()
    drag = {
      id: 0,
      mode: handle ? 'resize' : 'move',
      handle,
      box,
      startX: event.clientX,
      startY: event.clientY,
      stagePx: { width: rect.width, height: rect.height },
      frame: { width: layout.width, height: layout.height },
      zone: layout.safe_zone,
      project: editor.name,
      began: false,
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    document.addEventListener('keydown', onKey)
  }

  /** O nome do formato para o aviso: "Instagram Reels". */
  async function presetName(): Promise<string> {
    const id = (editor.spec?.output as Loose | undefined)?.preset
    try {
      await catalog.load()
    } catch {
      // sem o catálogo o aviso usa o identificador do formato
    }
    const preset = catalog.presets.find((candidate) => candidate.id === id)
    return preset ? `${preset.platform} ${preset.name}` : typeof id === 'string' ? id : 'formato'
  }

  /** Espera a próxima resposta de caixas do servidor depois de `before`; falso se ela não vier a tempo. */
  function nextBoxes(before: unknown): Promise<boolean> {
    return new Promise((resolve) => {
      let stop = () => {}
      const timer = setTimeout(() => {
        stop()
        resolve(false)
      }, SETTLE_TIMEOUT_MS)
      stop = watch(
        () => editor.boxes,
        (layout) => {
          if (layout === before) return
          clearTimeout(timer)
          stop()
          resolve(true)
        },
      )
    })
  }

  async function noticesFor(current: Drag, final: PlacedBox, fresh: boolean): Promise<string[]> {
    const lines: string[] = []
    const label = boxLabel(current.box)
    if (current.box.placement === 'region' && current.box.region) {
      lines.push(`${label} deixou de seguir a região “${current.box.region}”: mexer na região não a move mais.`)
    }
    // a conta do servidor vale quando as caixas novas chegaram; senão fica a do cliente, que é a mesma conta
    const server = fresh ? editor.boxes?.boxes.find((candidate) => candidate.index === current.box.index) : undefined
    const sides: SafeZoneSide[] = server ? server.outside_safe_zone : sidesOutside(final, current.zone, current.frame)
    if (sides.length > 0) lines.push(`${label} saiu da zona segura do ${await presetName()}, ${sidesText(sides)}.`)
    return lines
  }

  async function commit(current: Drag): Promise<void> {
    const final = live.value
    editor.endGesture()
    const overlay = (editor.spec?.overlays as Loose[] | undefined)?.[current.box.index]
    if (!final || !overlay || editor.name !== current.project) {
      live.value = null
      return
    }
    const patch = gesturePatch(current.mode, current.box, final.box, overlay, current.frame)
    editor.mutate((draft) => {
      const target = (draft.overlays as Loose[])[current.box.index]
      if (target) applyPatch(target, patch)
    })
    // grava na hora (o gesto direto vale como "salvar"); se havia outras mudanças sem salvar, elas vão junto.
    // Um 409 já abriu a faixa de escolha do disco: não há outro erro a mostrar por cima
    if (editor.dirty) await editor.save({ quiet: true })
    if (current.id !== serial || disposed) return
    const before = editor.boxes
    await editor.refreshBoxes()
    const fresh = editor.boxes !== before || (await nextBoxes(before))
    if (current.id !== serial || disposed) return
    live.value = null
    const lines = await noticesFor(current, final.box, fresh)
    if (current.id !== serial || disposed) return
    notices.value = lines
    noticeSpec = lines.length > 0 ? editor.specJson : null
    void realFrame.request()
  }

  // os avisos valem para a escolha e a spec do momento em que foram postos
  watch(
    () => editor.selectedOverlay,
    () => clearNotices(),
  )
  watch(
    () => editor.specJson,
    (json) => {
      if (noticeSpec !== null && json !== noticeSpec) clearNotices()
    },
  )

  onBeforeUnmount(() => {
    disposed = true
    cancel()
  })

  return { live, notices, begin, cancel, consumeClick }
}

/* Os comandos de edição da linha do tempo (cortar, remover, lift, duplicar, aparar, mudo/ocultar/bloquear, ir à
   próxima edição...). A barra de ferramentas e os atalhos de teclado chamam os mesmos, então o botão e a tecla nunca
   discordam. O que cada comando vira em operações é puro e mora em `lib/editorActions`; aqui só se executa e se avisa. */
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'
import { useTimelineStore } from '@/stores/timeline'
import { useToastsStore } from '@/stores/toasts'
import {
  planDuplicate,
  planRemove,
  planSplit,
  planTrackToggle,
  planTrim,
  shortcutTrack,
  v1ItemIds,
  type Plan,
} from '@/lib/editorActions'
import { edgeTimes, nextEdge, type TrackToggle } from '@/lib/timeline'

export function useEditorActions() {
  const editor = useEditorStore()
  const player = usePlayerStore()
  const timeline = useTimelineStore()
  const toasts = useToastsStore()

  function warn(message: string): void {
    toasts.push({ tone: 'error', title: message })
  }

  /** Executa as operações do plano como um comando só (um passo do desfazer); devolve se todas deram certo. */
  function run(plan: Plan): Promise<boolean> {
    if (plan.ok) return editor.applyOps(plan.ops)
    warn(plan.message)
    return Promise.resolve(false)
  }

  /** Planeja com a vista de agora; sem vista (a spec não abriu), não há o que editar. */
  function planned(make: (view: NonNullable<typeof editor.view>) => Plan): Promise<boolean> {
    const view = editor.view
    if (!view) return Promise.resolve(false)
    return run(make(view))
  }

  function split(): Promise<boolean> {
    return planned((view) => planSplit(view, editor.selectedItems, editor.playhead))
  }

  async function removeSelected(): Promise<boolean> {
    const done = await planned((view) => planRemove(view, editor.selectedItems))
    // os ids mudam de dono quando um item some, até se a remoção parou no meio: manter a seleção marcaria outro item
    editor.clearSelection()
    return done
  }

  /** O lift da V1 também fecha a lacuna: a V1 não tem buracos, então ele é o mesmo que remover. */
  async function lift(): Promise<boolean> {
    const hadV1 = editor.selectedItems.some((entry) => entry.trackId === 'V1')
    const done = await planned((view) => planRemove(view, editor.selectedItems, 'o lift'))
    editor.clearSelection()
    if (done && hadV1) toasts.push({ tone: 'success', title: 'A V1 não tem lacunas: o lift removeu o trecho (ripple).' })
    return done
  }

  function duplicateSelected(): Promise<boolean> {
    return planned((view) => planDuplicate(view, editor.selectedItems))
  }

  function trimTo(side: 'in' | 'out'): Promise<boolean> {
    return planned((view) => planTrim(view, editor.selectedItems, side, editor.playhead))
  }

  /** Mudo, ocultar ou bloquear. O botão do cabeçalho diz a trilha; o atalho usa a do item selecionado ou a sob o mouse. */
  function toggleTrack(field: TrackToggle, trackId?: string): Promise<boolean> {
    return planned((view) =>
      planTrackToggle(view, trackId ?? shortcutTrack(editor.selectedItems, timeline.hoverTrackId), field),
    )
  }

  /** Os itens que o clique de selecionar tudo marca: todos os trechos da V1. */
  function selectAllV1(): void {
    const view = editor.view
    if (!view) return
    if (view.tracks.find((track) => track.id === 'V1')?.locked) {
      warn('A trilha V1 está bloqueada (cadeado no cabeçalho).')
      return
    }
    editor.select(v1ItemIds(view))
  }

  /** Pula para a edição (emenda da V1) anterior ou seguinte ao cursor. */
  function jumpEdit(direction: -1 | 1): void {
    const view = editor.view
    if (!view) return
    const target = nextEdge(edgeTimes(view), editor.playhead, direction)
    if (target !== null) player.seek(target)
  }

  /** Anda `seconds` (negativo volta) sem parar nem começar a tocar. */
  function nudge(seconds: number): void {
    player.seek(editor.playhead + seconds)
  }

  return {
    split,
    removeSelected,
    lift,
    duplicateSelected,
    trimTo,
    toggleTrack,
    selectAllV1,
    jumpEdit,
    nudge,
  }
}

/* O teclado do editor: escuta as teclas na janela, descobre a ação pela tabela de atalhos (`stores/keymap`) e a
   executa. Também avisa o navegador quando a pessoa tenta fechar a aba com mudança não salva. Chamar uma vez, na tela
   do editor; os comandos de edição são os mesmos da barra de ferramentas (`useEditorActions`). */
import { onBeforeUnmount, onMounted } from 'vue'
import {
  comboFromEvent,
  isModifierKey,
  keyBelongsToTarget,
  WORKS_WHILE_TYPING,
  type ShortcutId,
} from '@/lib/keymap'
import { useEditorStore } from '@/stores/editor'
import { useKeymapStore, type ShortcutHandler } from '@/stores/keymap'
import { usePlayerStore } from '@/stores/player'
import { useTimelineStore } from '@/stores/timeline'
import { useToastsStore } from '@/stores/toasts'
import { useEditorActions } from './useEditorActions'

/** O mesmo A e V do painel Mídia quando ele não está na tela: dizem o que falta em vez de ficarem mudos. */
const NEEDS_MEDIA_PANEL = 'Selecione um arquivo no painel de mídia.'

export function useEditorShortcuts(): void {
  const editor = useEditorStore()
  const player = usePlayerStore()
  const timeline = useTimelineStore()
  const keymap = useKeymapStore()
  const toasts = useToastsStore()
  const actions = useEditorActions()

  const handlers: Record<ShortcutId, ShortcutHandler> = {
    play_pause: () => player.toggle(),
    pause: () => player.pause(),
    // segurar o J ou o L repetiria a tecla e dobraria a velocidade sem parar: só o primeiro toque vale
    play_reverse: (event) => {
      if (!event.repeat) player.bump(-1)
    },
    play_forward: (event) => {
      if (!event.repeat) player.bump(1)
    },
    step_back: () => player.stepFrame(-1),
    step_forward: () => player.stepFrame(1),
    prev_edit: () => actions.jumpEdit(-1),
    next_edit: () => actions.jumpEdit(1),
    go_start: () => {
      player.pause()
      player.goStart()
    },
    go_end: () => player.goEnd(),
    back_1s: () => actions.nudge(-1),
    forward_1s: () => actions.nudge(1),
    split: () => void actions.split(),
    remove_ripple: () => void actions.removeSelected(),
    lift: () => void actions.lift(),
    trim_in: () => void actions.trimTo('in'),
    trim_out: () => void actions.trimTo('out'),
    undo: () => void editor.undo(),
    redo: () => void editor.redo(),
    save: () => void editor.save(),
    duplicate: () => void actions.duplicateSelected(),
    select_all: () => actions.selectAllV1(),
    zoom_in: () => timeline.zoomIn(),
    zoom_out: () => timeline.zoomOut(),
    zoom_fit: () => timeline.zoomFit(),
    toggle_snap: () => void timeline.toggleSnap(),
    toggle_ripple: () => void timeline.toggleRipple(),
    clear_selection: () => editor.clearSelection(),
    show_shortcuts: () => keymap.openDialog(),
    media_append: () => toasts.push({ tone: 'error', title: NEEDS_MEDIA_PANEL }),
    media_insert: () => toasts.push({ tone: 'error', title: NEEDS_MEDIA_PANEL }),
    track_mute: () => void actions.toggleTrack('muted'),
    track_hide: () => void actions.toggleTrack('hidden'),
    track_lock: () => void actions.toggleTrack('locked'),
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.defaultPrevented || event.isComposing || editor.status !== 'ready' || isModifierKey(event.key)) return
    const combo = comboFromEvent(event)
    const ids = keymap.byCombo.get(combo)
    if (!ids) return
    if (keyBelongsToTarget(event.target, combo, ids.every((id) => WORKS_WHILE_TYPING.has(id)))) return
    event.preventDefault()
    for (const id of ids) (keymap.registered.get(id) ?? handlers[id])(event)
  }

  // sair da página com mudança não salva: o navegador pede confirmação
  function warnBeforeUnload(event: BeforeUnloadEvent): void {
    if (!editor.dirty) return
    event.preventDefault()
    event.returnValue = ''
  }

  onMounted(() => {
    window.addEventListener('keydown', onKeydown)
    window.addEventListener('beforeunload', warnBeforeUnload)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKeydown)
    window.removeEventListener('beforeunload', warnBeforeUnload)
  })
}

/** Registra o comando de uma ação enquanto o componente existir (o painel Mídia usa para o A e o V). */
export function useShortcutHandler(id: ShortcutId, handler: ShortcutHandler): void {
  const keymap = useKeymapStore()
  let unregister: (() => void) | null = null
  onMounted(() => {
    unregister = keymap.register(id, handler)
  })
  onBeforeUnmount(() => unregister?.())
}

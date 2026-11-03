/* Os gestos do painel Mídia que mudam o projeto (acrescentar ao fim da V1, inserir no cursor, soltar na linha do
   tempo, e os botões "+ Arquivo", Texto, Cartão, Logo e Música). Cada um vira operações pelo `applyOps` do store, num
   passo só do desfazer. O que cada gesto vira em operações é puro e mora em `lib/mediaInsert`; aqui só se executa e se avisa. */
import type { TimelineView } from '@/api'
import type { Plan } from '@/lib/editorActions'
import type { MediaEntry } from '@/lib/media'
import {
  parseMediaPayload,
  planAddCard,
  planAddFile,
  planAddLogo,
  planAddText,
  planAppend,
  planDrop,
  planInsertAtTime,
  planSetMusic,
} from '@/lib/mediaInsert'
import { useEditorStore } from '@/stores/editor'
import { useToastsStore } from '@/stores/toasts'
import { useEditorFilePicker } from './useEditorFilePicker'

export function useMediaActions() {
  const editor = useEditorStore()
  const toasts = useToastsStore()
  const pickFile = useEditorFilePicker()

  /** Executa o plano; o aviso de um plano que não vale vai para a pessoa em vez de a tela ficar muda. */
  function run(plan: Plan): Promise<boolean> {
    if (plan.ok) return editor.applyOps(plan.ops)
    toasts.push({ tone: 'error', title: plan.message })
    return Promise.resolve(false)
  }

  /** Planeja com a vista de agora; sem vista (a spec não abriu), não há onde inserir. */
  function planned(make: (view: TimelineView) => Plan): Promise<boolean> {
    const view = editor.view
    return view ? run(make(view)) : Promise.resolve(false)
  }

  function overlays(): unknown[] {
    const list = editor.get('overlays')
    return Array.isArray(list) ? list : []
  }

  /** O arquivo que a pessoa escolhe no navegador de arquivos do servidor, ou null se ela cancelar. */
  async function choosePath(): Promise<string | null> {
    return (await pickFile?.()) ?? null
  }

  return {
    /** Há um navegador de arquivos (o da tela do editor) para "+ Arquivo" e Música. */
    canPickFile: pickFile !== null,
    append: (entry: MediaEntry) => planned((view) => planAppend(view, entry)),
    insertAtPlayhead: (entry: MediaEntry) => planned((view) => planInsertAtTime(view, entry, editor.playhead)),
    /** Soltar na linha do tempo; `payload` é o texto que o arrastar levou. Texto que não é mídia não faz nada. */
    drop: (payload: string, hit: { trackId: string | null; time: number }) => {
      const entry = parseMediaPayload(payload)
      return entry ? planned((view) => planDrop(view, overlays(), entry, hit)) : Promise.resolve(false)
    },
    addText: () => planned((view) => planAddText(view, overlays(), editor.playhead)),
    addLogo: () => planned((view) => planAddLogo(view, overlays(), editor.playhead)),
    addCard: () => planned((view) => planAddCard(view)),
    async addFile(): Promise<boolean> {
      const path = await choosePath()
      return path ? planned((view) => planAddFile(view, editor.get('audio.music'), path)) : false
    },
    async addMusic(): Promise<boolean> {
      const path = await choosePath()
      return path ? run(planSetMusic(editor.get('audio.music'), path)) : false
    },
  }
}

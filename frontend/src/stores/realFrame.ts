/* O quadro real do cursor: a imagem que o pipeline de verdade (o mesmo do render) desenha para o instante do cursor,
   na resolução da prévia, que o palco mostra no lugar da composição aproximada. Pede o quadro ao servidor, consulta até
   ele ficar pronto e o devolve ao aproximado no instante em que a spec ou o cursor mudam: um quadro de outra spec ou de
   outro instante mentiria sobre o que o render fará. */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { api, errorMessage, type InstantFrame } from '@/api'
import { pruneEmpty } from '@/lib/editorPaths'
import { useEditorStore } from './editor'

/** De quanto em quanto tempo o quadro pendente é consultado: o servidor faz um quadro em décimos de segundo a alguns segundos. */
export const FRAME_POLL_MS = 400

export type RealFrameState = 'idle' | 'pending' | 'ready' | 'error'

/** O que o quadro pedido enxerga do editor: se algo disto mudar, o quadro já não vale. */
interface Requested {
  name: string
  spec: string
  playhead: number
}

export const useRealFrameStore = defineStore('realFrame', () => {
  const editor = useEditorStore()

  const state = ref<RealFrameState>('idle')
  /** O endereço da imagem do quadro pronto. */
  const url = ref('')
  /** O instante exato que o quadro mostra (na grade de quadros do vídeo), e não o que foi pedido. */
  const at = ref<number | null>(null)
  /** O que o quadro não mostra (uma legenda automática sem transcrição, por exemplo). */
  const notes = ref<string[]>([])
  /** A etapa em andamento e o percentual dela, enquanto o quadro é feito. */
  const label = ref('')
  const percent = ref(0)
  const error = ref('')

  // sobe a cada pedido e a cada invalidação: a resposta de um pedido que já não vale é descartada
  let ticket = 0
  let timer: ReturnType<typeof setTimeout> | null = null
  let requested: Requested | null = null

  function stopPolling(): void {
    if (timer) clearTimeout(timer)
    timer = null
  }

  function reset(): void {
    state.value = 'idle'
    url.value = ''
    at.value = null
    notes.value = []
    label.value = ''
    percent.value = 0
    error.value = ''
  }

  /** Volta à composição aproximada e para as consultas. Quem chama: a spec ou o cursor mudaram, ou o editor fechou. */
  function invalidate(): void {
    ticket += 1
    stopPolling()
    requested = null
    reset()
  }

  function fail(message: string): void {
    stopPolling()
    state.value = 'error'
    error.value = message
  }

  function take(answer: InstantFrame, name: string, mine: number): void {
    notes.value = answer.notes ?? []
    if (answer.t !== null && answer.t !== undefined) at.value = answer.t
    if (answer.status === 'ready') {
      if (answer.url) {
        stopPolling()
        state.value = 'ready'
        url.value = answer.url
      } else {
        fail('O servidor disse que o quadro está pronto, mas não mandou a imagem.')
      }
    } else if (answer.status === 'pending') {
      state.value = 'pending'
      label.value = answer.label ?? ''
      percent.value = answer.percent ?? 0
      stopPolling()
      timer = setTimeout(() => void poll(name, answer.key, mine), FRAME_POLL_MS)
    } else if (answer.status === 'error') {
      fail(answer.error || 'O servidor não conseguiu gerar o quadro.')
    } else {
      // superado por um pedido mais novo do mesmo projeto (de outra aba ou da CLI): não é mais o quadro desta tela
      invalidate()
    }
  }

  async function poll(name: string, key: string, mine: number): Promise<void> {
    timer = null
    if (mine !== ticket) return
    try {
      const answer = await api.editor.frame.get(name, key)
      if (mine !== ticket) return
      take(answer, name, mine)
    } catch (caught) {
      if (mine !== ticket) return
      fail(errorMessage(caught))
    }
  }

  /** Pede o quadro do cursor para a edição que está na tela (salva ou não). Um pedido novo toma o lugar do anterior. */
  async function request(): Promise<void> {
    editor.flushPendingEdits()
    const name = editor.name
    const spec = editor.spec
    if (!name || !spec || !editor.view) return
    stopPolling()
    const mine = (ticket += 1)
    requested = { name, spec: editor.specJson, playhead: editor.playhead }
    reset()
    state.value = 'pending'
    label.value = 'Pedindo o quadro'
    try {
      const answer = await api.editor.frame.request(name, pruneEmpty(spec), requested.playhead)
      if (mine !== ticket) return
      take(answer, name, mine)
    } catch (caught) {
      if (mine !== ticket) return
      fail(errorMessage(caught))
    }
  }

  /** O botão do player: pede o quadro, ou volta à composição aproximada se ele já está na tela ou a caminho. */
  function toggle(): Promise<void> {
    if (state.value === 'idle' || state.value === 'error') return request()
    invalidate()
    return Promise.resolve()
  }

  // qualquer mudança na spec ou no cursor devolve a tela à composição aproximada; o pedido que acabou de ser feito
  // olha para o que ele mesmo viu, então um aviso atrasado do que ele já sabia não o derruba
  watch([() => editor.specJson, () => editor.playhead, () => editor.name], () => {
    if (!requested) return
    if (editor.name !== requested.name || editor.specJson !== requested.spec || editor.playhead !== requested.playhead) invalidate()
  })

  return { state, url, at, notes, label, percent, error, request, toggle, invalidate }
})

import { defineStore } from 'pinia'
import { computed, shallowRef } from 'vue'

export interface ConfirmOptions {
  title: string
  description?: string
  /** Aviso em destaque dentro do diálogo. */
  warning?: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: 'default' | 'danger'
}

export interface PendingConfirmation {
  id: number
  options: ConfirmOptions
}

interface Entry extends PendingConfirmation {
  resolve: (accepted: boolean) => void
}

/** Fila de confirmações: `ask` faz o papel do `window.confirm` (promessa de sim ou não) e o `ConfirmHost` desenha o diálogo. */
export const useConfirmStore = defineStore('confirm', () => {
  const queue = shallowRef<Entry[]>([])
  let counter = 0

  /** A confirmação na tela agora; as seguintes esperam a vez. */
  const current = computed<PendingConfirmation | null>(() => {
    const head = queue.value[0]
    return head ? { id: head.id, options: head.options } : null
  })

  function ask(options: ConfirmOptions): Promise<boolean> {
    return new Promise((resolve) => {
      counter += 1
      queue.value = [...queue.value, { id: counter, options, resolve }]
    })
  }

  /** Responde à confirmação da vez e passa para a próxima. */
  function answer(accepted: boolean): void {
    const head = queue.value[0]
    if (!head) return
    queue.value = queue.value.slice(1)
    head.resolve(accepted)
  }

  return { current, ask, answer }
})

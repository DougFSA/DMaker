import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastTone = 'success' | 'error' | 'info'

export interface Toast {
  id: number
  tone: ToastTone
  title: string
  description?: string
  /** Ação opcional no próprio aviso (ex.: "Assistir" quando o render termina). */
  action?: { label: string; run: () => void }
}

export type ToastInput = Omit<Toast, 'id' | 'tone'> & { tone?: ToastTone }

const LIFETIME_MS: Record<ToastTone, number> = { success: 6000, info: 6000, error: 10000 }

export const useToastsStore = defineStore('toasts', () => {
  const items = ref<Toast[]>([])
  let nextId = 1

  function dismiss(id: number): void {
    items.value = items.value.filter((toast) => toast.id !== id)
  }

  function push(input: ToastInput): number {
    const toast: Toast = { ...input, id: nextId++, tone: input.tone ?? 'info' }
    items.value = [...items.value, toast]
    // erro fica mais tempo na tela: quem lê precisa de tempo para entender o que houve
    setTimeout(() => dismiss(toast.id), LIFETIME_MS[toast.tone])
    return toast.id
  }

  return { items, push, dismiss }
})

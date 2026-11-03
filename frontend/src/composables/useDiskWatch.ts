/* Faz o editor aberto perceber que o `spec.json` mudou no disco por fora (o Claude pelo MCP, o agente local, a CLI):
   consulta a revisão de poucos em poucos segundos, só com a aba visível, e de novo no instante em que ela volta a
   ficar visível. O que fazer com a mudança é do store (`checkDisk`); aqui só mora o relógio. Chamar uma vez, na tela
   do editor. */
import { onBeforeUnmount, onMounted } from 'vue'
import { DISK_CHECK_INTERVAL_MS, useEditorStore } from '@/stores/editor'

export function useDiskWatch(intervalMs: number = DISK_CHECK_INTERVAL_MS): void {
  const editor = useEditorStore()
  let timer: ReturnType<typeof setInterval> | null = null

  const visible = () => typeof document === 'undefined' || document.visibilityState === 'visible'

  function check(): void {
    if (visible()) void editor.checkDisk()
  }

  onMounted(() => {
    timer = setInterval(check, intervalMs)
    document.addEventListener('visibilitychange', check)
  })

  onBeforeUnmount(() => {
    if (timer) clearInterval(timer)
    timer = null
    document.removeEventListener('visibilitychange', check)
  })
}

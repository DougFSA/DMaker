import { useConfirmStore, type ConfirmOptions } from '@/stores/confirm'

/**
 * Pergunta "tem certeza?" com o diálogo da interface; resolve `true` se a pessoa confirmou.
 *
 *     const confirm = useConfirm()
 *     if (!(await confirm({ title: 'Remover a voz?', tone: 'danger', confirmLabel: 'Remover' }))) return
 */
export function useConfirm(): (options: ConfirmOptions) => Promise<boolean> {
  const store = useConfirmStore()
  return (options) => store.ask(options)
}

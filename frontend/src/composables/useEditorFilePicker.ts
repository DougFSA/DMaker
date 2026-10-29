import { inject, provide, ref, watch, type InjectionKey, type Ref } from 'vue'

/** Abre o navegador de arquivos do servidor e devolve o caminho escolhido, ou null se a pessoa cancelou. */
export type PickFile = () => Promise<string | null>

const FILE_PICKER: InjectionKey<PickFile> = Symbol('editor-file-picker')

export interface EditorFilePicker {
  /** Liga ao `v-model:open` do `FileBrowserDialog` que a tela do editor desenha uma vez só. */
  open: Ref<boolean>
  /** Liga ao `@select` do mesmo diálogo. */
  onSelect: (paths: string[]) => void
}

/**
 * A tela do editor chama isto uma vez: os campos de arquivo de qualquer painel passam a poder escolher um arquivo
 * do servidor sem cada um carregar o seu próprio diálogo.
 */
export function provideEditorFilePicker(): EditorFilePicker {
  const open = ref(false)
  let waiting: ((path: string | null) => void) | null = null

  function settle(path: string | null): void {
    const resolve = waiting
    waiting = null
    resolve?.(path)
  }

  provide(FILE_PICKER, () => {
    settle(null) // um pedido ainda aberto é dado como cancelado
    return new Promise<string | null>((resolve) => {
      waiting = resolve
      open.value = true
    })
  })

  // fechar o diálogo sem escolher (Cancelar, Esc) também responde ao pedido
  watch(open, (isOpen) => {
    if (!isOpen) settle(null)
  })

  return { open, onSelect: (paths) => settle(paths[0] ?? null) }
}

/** O seletor de arquivos da tela do editor; null fora dela (o campo então fica só com o texto). */
export function useEditorFilePicker(): PickFile | null {
  return inject(FILE_PICKER, null)
}

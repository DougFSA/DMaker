import { reactive } from 'vue'
import { stableKey } from '@/lib/editorSpec'

/** Até esta quantidade de itens os cartões começam abertos; passou disso, começam recolhidos (200 formulários travariam a tela). */
export const OPEN_CARDS_LIMIT = 6

/**
 * Quais cartões de uma lista (trechos, sobreposições) estão abertos. O estado acompanha o item, não a posição: subir
 * um trecho leva o cartão aberto junto. `initialCount` decide o padrão de quem ainda não foi aberto nem fechado à mão.
 */
export function useCardExpansion(initialCount: number) {
  const startOpen = initialCount <= OPEN_CARDS_LIMIT
  const chosen = reactive(new Map<number, boolean>())

  return {
    isOpen: (item: unknown): boolean => chosen.get(stableKey(item)) ?? startOpen,
    setOpen: (item: unknown, open: boolean): void => {
      chosen.set(stableKey(item), open)
    },
    /** Abre o item recém-criado, para a pessoa já ver os campos dele. */
    reveal: (item: unknown): void => {
      chosen.set(stableKey(item), true)
    },
  }
}

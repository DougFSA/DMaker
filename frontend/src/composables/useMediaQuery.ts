import { onScopeDispose, ref, type Ref } from 'vue'

/** Abaixo de 768 px (celular em pé) a barra lateral deixa de ocupar uma coluna e vira gaveta. */
export const NARROW_QUERY = '(max-width: 767.98px)'

/**
 * Acompanha uma media query do navegador. O valor inicial é lido na hora, antes da primeira pintura, para a tela
 * não nascer com o layout largo e trocar depois; sem `matchMedia` (ambiente sem janela), vale sempre `false`.
 */
export function useMediaQuery(query: string): Ref<boolean> {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return ref(false)

  const media = window.matchMedia(query)
  const matches = ref(media.matches)
  const onChange = (event: MediaQueryListEvent): void => {
    matches.value = event.matches
  }
  media.addEventListener('change', onChange)
  onScopeDispose(() => media.removeEventListener('change', onChange))
  return matches
}

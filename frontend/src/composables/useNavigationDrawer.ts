import { onScopeDispose, watch, type Ref } from 'vue'
import { useRoute } from 'vue-router'
import { useWorkspaceStore } from '@/stores/workspace'

/** O botão da barra de cima que abre a gaveta: é para ele que o foco volta quando ela fecha. */
export const NAVIGATION_TOGGLE_ID = 'navigation-toggle'

/** Classe do `<html>` que trava a rolagem da página enquanto a gaveta está aberta (o CSS dela fica em base.css). */
const SCROLL_LOCK_CLASS = 'is-scroll-locked'

/**
 * Comportamento da gaveta de navegação em tela estreita: fecha ao navegar e com Esc, leva o foco para dentro ao abrir
 * e de volta ao botão ao fechar, e trava a rolagem da página por baixo. O estado (aberta ou fechada) mora no
 * `workspace`; aqui fica só o que mexe no documento. Devolve o tratador de clique da gaveta, que a fecha ao tocar num
 * link, inclusive no da página em que a pessoa já está (a rota não muda e o vigia de rota não veria nada).
 */
export function useNavigationDrawer(drawer: Ref<HTMLElement | null>): { onDrawerClick: (event: MouseEvent) => void } {
  const workspace = useWorkspaceStore()
  const route = useRoute()

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && !event.defaultPrevented) workspace.closeDrawer()
  }

  function unlock(): void {
    document.removeEventListener('keydown', onKeydown)
    document.documentElement.classList.remove(SCROLL_LOCK_CLASS)
  }

  // `flush: 'post'`: o DOM já foi atualizado, então o `inert` já saiu da gaveta (aberta) ou do conteúdo (fechada) e o
  // foco pode ir; antes disso `focus()` falharia, porque um elemento inerte não recebe foco
  watch(
    () => workspace.drawerOpen,
    (open) => {
      if (open) {
        document.addEventListener('keydown', onKeydown)
        document.documentElement.classList.add(SCROLL_LOCK_CLASS)
        drawer.value?.focus({ preventScroll: true })
        return
      }
      unlock()
      // ao alargar a janela o botão passa a recolher a barra; mexer no foco ali só atrapalharia
      if (workspace.narrow) document.getElementById(NAVIGATION_TOGGLE_ID)?.focus({ preventScroll: true })
    },
    { flush: 'post' },
  )

  watch(
    () => route.fullPath,
    () => workspace.closeDrawer(),
  )

  onScopeDispose(unlock)

  function onDrawerClick(event: MouseEvent): void {
    if (event.target instanceof Element && event.target.closest('a')) workspace.closeDrawer()
  }

  return { onDrawerClick }
}

/* Apoio dos testes das views: monta o app na rota pedida, com o router de verdade e a view carregada sob demanda. */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { expect } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, RouterView, type Router } from 'vue-router'
import { createAppRouter } from '@/router'

export interface MountedRoute {
  wrapper: VueWrapper
  router: Router
}

export async function mountRoute(path: string): Promise<MountedRoute> {
  setActivePinia(createPinia())
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const Host = defineComponent({ render: () => h(RouterView) })
  const wrapper = mount(Host, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

/** O que toda view "em construção" precisa mostrar: o nome da tela e o caminho de volta para a clássica. */
export function expectUnderConstruction(wrapper: VueWrapper, title: string, classic: string): void {
  expect(wrapper.text()).toContain(`${title}: em construção`)
  expect(wrapper.text()).toContain(classic)
  expect(wrapper.find('a[href="/classica"]').exists()).toBe(true)
}

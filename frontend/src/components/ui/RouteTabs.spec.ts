import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import RouteTabs from './RouteTabs.vue'

const items = [
  { to: '/voz', label: 'Vozes' },
  { to: '/voz/narracao', label: 'Narração' },
]

async function mountAt(path: string) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  return mount(RouteTabs, { props: { items, label: 'Seções da Voz' }, global: { plugins: [router] } })
}

describe('RouteTabs', () => {
  it('é uma navegação com nome e um link por aba', async () => {
    const wrapper = await mountAt('/voz')
    expect(wrapper.find('nav').attributes('aria-label')).toBe('Seções da Voz')
    const links = wrapper.findAll('a')
    expect(links.map((link) => [link.text(), link.attributes('href')])).toEqual([
      ['Vozes', '/voz'],
      ['Narração', '/voz/narracao'],
    ])
  })

  it('marca como ativa só a aba da rota atual e avisa a página atual ao leitor de tela', async () => {
    const wrapper = await mountAt('/voz/narracao')
    const [first, second] = wrapper.findAll('a')
    expect(first?.classes()).not.toContain('is-active')
    expect(second?.classes()).toContain('is-active')
    expect(second?.attributes('aria-current')).toBe('page')
    expect(first?.attributes('aria-current')).toBeUndefined()
  })

  it('a primeira aba (a raiz da área) não fica ativa nas irmãs', async () => {
    const wrapper = await mountAt('/voz')
    const [first, second] = wrapper.findAll('a')
    expect(first?.classes()).toContain('is-active')
    expect(second?.classes()).not.toContain('is-active')
  })
})

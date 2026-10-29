import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '@/router'
import UnderConstruction from './UnderConstruction.vue'

async function mountIt() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/projetos')
  await router.isReady()
  return mount(UnderConstruction, {
    props: {
      title: 'Narração',
      description: 'Escrever o roteiro e ouvir cada fala.',
      classic: 'aba Voz, seção Narração',
      icon: 'mic',
    },
    global: { plugins: [router] },
  })
}

describe('UnderConstruction', () => {
  it('diz que a tela está em construção e o que ela vai trazer', async () => {
    const wrapper = await mountIt()
    expect(wrapper.text()).toContain('Narração: em construção')
    expect(wrapper.text()).toContain('Escrever o roteiro e ouvir cada fala.')
    expect(wrapper.find('.badge').text()).toBe('em construção')
  })

  it('leva ao equivalente na clássica, dizendo onde ele fica', async () => {
    const wrapper = await mountIt()
    expect(wrapper.text()).toContain('aba Voz, seção Narração')
    const classic = wrapper.find('a[href="/classica"]')
    expect(classic.exists()).toBe(true)
    expect(classic.text()).toContain('interface clássica')
  })

  it('permite voltar para Projetos', async () => {
    const wrapper = await mountIt()
    expect(wrapper.find('a[href="/projetos"]').exists()).toBe(true)
  })

  it('o texto de tela não usa travessão', async () => {
    const wrapper = await mountIt()
    expect(wrapper.text()).not.toMatch(/[—–]/)
  })
})

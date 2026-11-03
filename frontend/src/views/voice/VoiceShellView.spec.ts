import { describe, expect, it } from 'vitest'
import { mountRoute } from '@/test/routes'

describe('VoiceShellView', () => {
  it('mostra o título da área e uma aba para cada seção, em ordem', async () => {
    const { wrapper } = await mountRoute('/voz')
    expect(wrapper.find('h1').text()).toBe('Voz')
    const tabs = wrapper.findAll('nav[aria-label="Seções da Voz"] a')
    expect(tabs.map((tab) => [tab.text(), tab.attributes('href')])).toEqual([
      ['Vozes', '/voz'],
      ['Narração', '/voz/narracao'],
      ['Pronúncia', '/voz/pronuncia'],
      ['Isolar voz', '/voz/isolar'],
      ['Corrigir fala', '/voz/corrigir'],
      ['Trocar voz', '/voz/trocar'],
    ])
  })

  it('a aba ativa é a da rota e muda ao navegar, sem sair da casca', async () => {
    const { wrapper, router } = await mountRoute('/voz')
    const active = () => wrapper.findAll('nav a.is-active').map((tab) => tab.text())
    expect(active()).toEqual(['Vozes'])
    await router.push('/voz/pronuncia')
    expect(active()).toEqual(['Pronúncia'])
    expect(wrapper.findAll('h1')).toHaveLength(1)
  })
})

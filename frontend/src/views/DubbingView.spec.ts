import { describe, expect, it } from 'vitest'
import { expectUnderConstruction, mountRoute } from '@/test/routes'

describe('DubbingView (/dublagem)', () => {
  it('mostra a tela em construção com o caminho para a clássica', async () => {
    const { wrapper } = await mountRoute('/dublagem')
    expect(wrapper.find('h1').text()).toBe('Dublagem')
    expectUnderConstruction(wrapper, 'Dublagem', 'aba Voz, seção Dublar')
  })
})

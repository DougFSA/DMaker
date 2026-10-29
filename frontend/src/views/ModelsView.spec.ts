import { describe, expect, it } from 'vitest'
import { expectUnderConstruction, mountRoute } from '@/test/routes'

describe('ModelsView (/modelos)', () => {
  it('mostra a tela em construção com o caminho para a clássica', async () => {
    const { wrapper } = await mountRoute('/modelos')
    expect(wrapper.find('h1').text()).toBe('Modelos')
    expectUnderConstruction(wrapper, 'Modelos', 'aba Modelos')
  })
})

import { describe, expect, it } from 'vitest'
import { expectUnderConstruction, mountRoute } from '@/test/routes'

describe('QueueView (/fila)', () => {
  it('mostra a tela em construção com o caminho para a clássica', async () => {
    const { wrapper } = await mountRoute('/fila')
    expect(wrapper.find('h1').text()).toBe('Fila')
    expectUnderConstruction(wrapper, 'Fila', 'aba Voz, seção Fila de narrações')
  })
})

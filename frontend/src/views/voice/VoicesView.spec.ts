import { describe, it } from 'vitest'
import { expectUnderConstruction, mountRoute } from '@/test/routes'

describe('VoicesView (/voz)', () => {
  it('mostra a tela em construção com o caminho para a clássica', async () => {
    const { wrapper } = await mountRoute('/voz')
    expectUnderConstruction(wrapper, 'Vozes', 'aba Voz, seção Vozes')
  })
})

import { describe, it } from 'vitest'
import { expectUnderConstruction, mountRoute } from '@/test/routes'

describe('NarrationView (/voz/narracao)', () => {
  it('mostra a tela em construção com o caminho para a clássica', async () => {
    const { wrapper } = await mountRoute('/voz/narracao')
    expectUnderConstruction(wrapper, 'Narração', 'aba Voz, seção Narração')
  })
})

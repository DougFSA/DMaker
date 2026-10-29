import { describe, it } from 'vitest'
import { expectUnderConstruction, mountRoute } from '@/test/routes'

describe('SwapVoiceView (/voz/trocar)', () => {
  it('mostra a tela em construção com o caminho para a clássica', async () => {
    const { wrapper } = await mountRoute('/voz/trocar')
    expectUnderConstruction(wrapper, 'Trocar voz', 'aba Voz, seção Trocar voz')
  })
})

import { describe, it } from 'vitest'
import { expectUnderConstruction, mountRoute } from '@/test/routes'

describe('FixSpeechView (/voz/corrigir)', () => {
  it('mostra a tela em construção com o caminho para a clássica', async () => {
    const { wrapper } = await mountRoute('/voz/corrigir')
    expectUnderConstruction(wrapper, 'Corrigir fala', 'aba Voz, seção Corrigir fala')
  })
})

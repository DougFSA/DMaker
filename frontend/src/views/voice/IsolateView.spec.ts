import { describe, it } from 'vitest'
import { expectUnderConstruction, mountRoute } from '@/test/routes'

describe('IsolateView (/voz/isolar)', () => {
  it('mostra a tela em construção com o caminho para a clássica', async () => {
    const { wrapper } = await mountRoute('/voz/isolar')
    expectUnderConstruction(wrapper, 'Isolar voz', 'aba Voz, seção Isolar voz')
  })
})

import { describe, it } from 'vitest'
import { expectUnderConstruction, mountRoute } from '@/test/routes'

describe('PronunciationView (/voz/pronuncia)', () => {
  it('mostra a tela em construção com o caminho para a clássica', async () => {
    const { wrapper } = await mountRoute('/voz/pronuncia')
    expectUnderConstruction(wrapper, 'Pronúncia', 'aba Voz, seção Pronúncia')
  })
})

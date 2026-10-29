import { describe, expect, it } from 'vitest'
import { expectUnderConstruction, mountRoute } from '@/test/routes'

describe('EditorView (/editor/:name)', () => {
  it('abre com o nome do projeto da URL', async () => {
    const { wrapper, router } = await mountRoute('/editor/meu%20video')
    expect(router.currentRoute.value.name).toBe('editor')
    expect(router.currentRoute.value.params.name).toBe('meu video')
    expect(wrapper.find('h1').text()).toBe('Editor')
    expect(wrapper.text()).toContain('Projeto meu video')
    expectUnderConstruction(wrapper, 'Editor', 'aba Linha do tempo')
  })

  it('o item do menu lateral (/editor, sem nome) pede para escolher um projeto', async () => {
    const { wrapper, router } = await mountRoute('/editor')
    expect(router.currentRoute.value.name).toBe('editor')
    expect(router.currentRoute.value.params.name).toBeFalsy()
    expect(wrapper.text()).toContain('Escolha um projeto para editar.')
  })
})

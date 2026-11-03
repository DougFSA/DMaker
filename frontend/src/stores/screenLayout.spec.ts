import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EDITING_AREAS, builtinLayouts } from '@/lib/editorLayout'
import { reply, routedFetch, type RoutedFetch } from '@/test/routedFetch'
import { useConfirmStore } from './confirm'
import { CURRENT_LAYOUT_KEY, useScreenLayoutStore } from './screenLayout'
import { useToastsStore } from './toasts'

const mine = { version: 1, areas: { ...EDITING_AREAS }, sizes: { 'col-left': 333 }, hidden: ['progress', 'filters'] }

let server: RoutedFetch

function fresh() {
  setActivePinia(createPinia())
  return useScreenLayoutStore()
}

beforeEach(() => {
  localStorage.clear()
  server = routedFetch({
    'GET /api/layouts': { layouts: { 'Meu layout': mine } },
    'PUT /api/layouts/Foco': { ok: true },
    'DELETE /api/layouts/Meu%20layout': { ok: true },
  })
})
afterEach(() => vi.unstubAllGlobals())

describe('o layout atual', () => {
  it('sem nada guardado, começa no Edição embutido', () => {
    const layouts = fresh()
    expect(layouts.name).toBe('Edição')
    expect(layouts.layout).toEqual(builtinLayouts().Edição)
    expect(layouts.modified).toBe(false)
    expect(layouts.isBuiltin).toBe(true)
  })

  it('volta como estava depois de recarregar, e no formato da interface clássica', () => {
    const layouts = fresh()
    layouts.choose('Player')
    layouts.setHidden('media', true)
    const stored = JSON.parse(localStorage.getItem(CURRENT_LAYOUT_KEY)!)
    expect(stored.name).toBe('Player')
    expect(stored.layout.sizes['row-top']).toBe(0.72)
    expect(stored.layout.hidden).toContain('media')

    const again = fresh()
    expect(again.name).toBe('Player')
    expect(again.isHidden('media')).toBe(true)
  })

  it('lê o que a interface clássica guardou', () => {
    localStorage.setItem(
      CURRENT_LAYOUT_KEY,
      JSON.stringify({ name: 'Efeitos', layout: { version: 1, areas: EDITING_AREAS, sizes: { 'col-left': 420 }, hidden: ['progress', 'media'] } }),
    )
    const layouts = fresh()
    expect(layouts.name).toBe('Efeitos')
    expect(layouts.isHidden('media')).toBe(true)
    expect(layouts.layout.sizes['col-left']).toBe(420)
  })

  it('o que está guardado e é lixo é ignorado', () => {
    localStorage.setItem(CURRENT_LAYOUT_KEY, 'isto não é json')
    expect(fresh().name).toBe('Edição')
    localStorage.setItem(CURRENT_LAYOUT_KEY, '"texto"')
    expect(fresh().name).toBe('Edição')
  })

  it('quem escondeu filtros ou mídia antes do layout de tela continua com eles escondidos', () => {
    localStorage.setItem('dmaker.editor.hiddenPanels', '["media"]')
    const layouts = fresh()
    expect(layouts.isHidden('media')).toBe(true)
    expect(layouts.isHidden('filters')).toBe(false)
    expect(layouts.name).toBe('Edição')
  })
})

describe('escolher, mexer e restaurar', () => {
  it('escolher um embutido troca tudo; nome que não existe não muda nada', () => {
    const layouts = fresh()
    expect(layouts.choose('Áudio')?.sizes['row-top']).toBe(0.16)
    expect(layouts.name).toBe('Áudio')
    expect(layouts.choose('Não existe')).toBeNull()
    expect(layouts.name).toBe('Áudio')
  })

  it('esconder, mostrar e alternar um painel', () => {
    const layouts = fresh()
    layouts.setHidden('filters', true)
    expect(layouts.isHidden('filters')).toBe(true)
    layouts.toggle('filters')
    expect(layouts.isHidden('filters')).toBe(false)
    layouts.toggle('media')
    layouts.toggle('media')
    expect(layouts.layout.hidden).toEqual(['progress'])
  })

  it('trocar dois painéis muda os encaixes e marca o layout como alterado', () => {
    const layouts = fresh()
    layouts.swap('player', 'timeline')
    expect(layouts.layout.areas['top-center']).toBe('timeline')
    expect(layouts.layout.areas.bottom).toBe('player')
    expect(layouts.modified).toBe(true)
    layouts.swap('player', 'timeline')
    expect(layouts.modified).toBe(false)
  })

  it('o tamanho de um divisor fica dentro da faixa', () => {
    const layouts = fresh()
    layouts.setSize('col-left', 5000)
    expect(layouts.layout.sizes['col-left']).toBe(560)
    layouts.setSize('row-top', 0.5)
    expect(layouts.layout.sizes['row-top']).toBe(0.5)
    expect(layouts.modified).toBe(true)
  })

  it('restaurar o padrão volta ao Edição embutido, com tudo no lugar', () => {
    const layouts = fresh()
    layouts.choose('Revisão')
    layouts.swap('player', 'media')
    layouts.restoreDefault()
    expect(layouts.name).toBe('Edição')
    expect(layouts.layout).toEqual(builtinLayouts().Edição)
    expect(layouts.modified).toBe(false)
  })
})

describe('layouts salvos', () => {
  it('lê do servidor os que a pessoa salvou e os escolhe pelo nome', async () => {
    const layouts = fresh()
    await layouts.loadSaved()
    expect(layouts.savedNames).toEqual(['Meu layout'])
    expect(layouts.choose('Meu layout')?.sizes['col-left']).toBe(333)
    expect(layouts.isHidden('filters')).toBe(true)
    expect(layouts.isBuiltin).toBe(false)
    expect(layouts.modified).toBe(false)
  })

  it('sem resposta do servidor, a lista fica vazia e os embutidos continuam valendo', async () => {
    server.set('GET /api/layouts', reply(500, { detail: 'fora do ar' }))
    const layouts = fresh()
    await layouts.loadSaved()
    expect(layouts.savedNames).toEqual([])
    expect(layouts.savedLoaded).toBe(true)
    expect(layouts.choose('Voz')).not.toBeNull()
  })

  it('salvar como grava o layout de agora no servidor e passa a usá-lo', async () => {
    const layouts = fresh()
    layouts.setSize('col-right', 300)
    layouts.swap('media', 'filters')
    server.set('GET /api/layouts', { layouts: { Foco: { ...layouts.layout } } })
    expect(await layouts.saveAs('  Foco ')).toBe(true)

    const sent = server.to('PUT /api/layouts/Foco')[0]!.body as { sizes: Record<string, number>; areas: Record<string, string> }
    expect(sent.sizes['col-right']).toBe(300)
    expect(sent.areas['top-left']).toBe('media')
    expect(layouts.name).toBe('Foco')
    expect(layouts.savedNames).toEqual(['Foco'])
    expect(layouts.modified).toBe(false)
    expect(useToastsStore().items.at(-1)?.title).toBe('Layout salvo')
  })

  it('não salva com nome em branco nem com o nome de um embutido', async () => {
    const layouts = fresh()
    expect(await layouts.saveAs('   ')).toBe(false)
    expect(await layouts.saveAs('Edição')).toBe(false)
    expect(server.to('PUT /api/layouts/Edi%C3%A7%C3%A3o')).toHaveLength(0)
    expect(useToastsStore().items.at(-1)?.title).toContain('embutido')
  })

  it('o servidor que recusa vira aviso, e o layout atual não muda de nome', async () => {
    server.set('PUT /api/layouts/Foco', reply(400, { detail: 'painel desconhecido: x' }))
    const layouts = fresh()
    expect(await layouts.saveAs('Foco')).toBe(false)
    expect(layouts.name).toBe('Edição')
    expect(useToastsStore().items.at(-1)).toMatchObject({ tone: 'error', title: 'Não foi possível salvar o layout' })
  })

  it('excluir o salvo em uso pergunta antes, apaga no servidor e volta ao padrão', async () => {
    const layouts = fresh()
    await layouts.loadSaved()
    layouts.choose('Meu layout')
    server.set('GET /api/layouts', { layouts: {} })
    const pending = layouts.removeCurrent()
    await flushPromises()
    expect(useConfirmStore().current?.options.title).toContain('Meu layout')
    useConfirmStore().answer(true)
    expect(await pending).toBe(true)

    expect(server.to('DELETE /api/layouts/Meu%20layout')).toHaveLength(1)
    expect(layouts.name).toBe('Edição')
    expect(layouts.savedNames).toEqual([])
  })

  it('se a pessoa desiste na confirmação, nada é apagado', async () => {
    const layouts = fresh()
    await layouts.loadSaved()
    layouts.choose('Meu layout')
    const pending = layouts.removeCurrent()
    await flushPromises()
    useConfirmStore().answer(false)
    expect(await pending).toBe(false)
    expect(server.to('DELETE /api/layouts/Meu%20layout')).toHaveLength(0)
    expect(layouts.name).toBe('Meu layout')
  })

  it('um embutido não se exclui e nem chega a perguntar', async () => {
    const layouts = fresh()
    expect(await layouts.removeCurrent()).toBe(false)
    expect(useConfirmStore().current).toBeNull()
    expect(useToastsStore().items.at(-1)?.title).toContain('embutidos')
  })
})

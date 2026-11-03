import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { projectSpec } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import OverlaysSection from './OverlaysSection.vue'

afterEach(() => vi.unstubAllGlobals())

type Mounted = Awaited<ReturnType<typeof mountEditorPart>>
const cards = (wrapper: Mounted) => wrapper.findAll('article')
const button = (wrapper: Mounted, label: string) =>
  wrapper.findAll('button').find((candidate) => candidate.attributes('aria-label') === label || candidate.text() === label)

function withOverlays(overlays: unknown[], extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { ...projectSpec(), overlays, ...extra }
}

describe('OverlaysSection', () => {
  it('mostra um cartão por sobreposição com o resumo (o texto, o logo ou o arquivo)', async () => {
    const opened = await openEditor(
      withOverlays([
        { type: 'text', text: 'Olá, mundo', role: 'title' },
        { type: 'image', src: 'logo' },
        { type: 'video', src: 'C:/midia/pip.mp4' },
        { type: 'progress-bar' },
      ]),
    )
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    expect(cards(wrapper)).toHaveLength(4)
    const summaries = cards(wrapper).map((card) => card.find('.card__summary').text())
    expect(summaries).toEqual(['Olá, mundo', 'logo da marca', 'pip.mp4', 'sem conteúdo ainda'])
  })

  it('sem sobreposições, diz o que cabe aqui', async () => {
    const opened = await openEditor(withOverlays([]))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    expect(cards(wrapper)).toHaveLength(0)
    expect(wrapper.text()).toContain('Sem sobreposições ainda')
  })

  it('adiciona cada tipo e abre o cartão novo', async () => {
    const opened = await openEditor(withOverlays([]))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    await button(wrapper, 'Adicionar texto')?.trigger('click')
    await button(wrapper, 'Adicionar barra de progresso')?.trigger('click')
    const overlays = opened.store.get('overlays') as Array<Record<string, unknown>>
    expect(overlays.map((overlay) => overlay.type)).toEqual(['text', 'progress-bar'])
    expect(cards(wrapper)[0]?.text()).toContain('Papel')
    expect(cards(wrapper)[1]?.text()).toContain('Altura (px)')
  })

  it('os campos do texto: papel, posição automática, animação padrão', async () => {
    const opened = await openEditor(withOverlays([{ type: 'text', text: 'Oi', role: 'cta', start: 1 }]))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    const texts = cards(wrapper)[0]?.findAll('select').map((select) => select.findAll('option').map((o) => o.text()))
    // tipo, papel, posição, animação
    expect(texts?.[1]).toContain('Chamada para ação')
    expect(texts?.[2]).toEqual(['Automática', 'Topo', 'Centro', 'Base'])
    expect(texts?.[3]?.[0]).toBe('Padrão')
  })

  it('imagem: escolher um logo grava a variante; "Personalizado" mostra o campo do arquivo', async () => {
    const opened = await openEditor(withOverlays([{ type: 'image', src: 'logo', position: 'top-right' }]))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    const origin = cards(wrapper)[0]?.findAll('select').find((select) => select.findAll('option').some((o) => o.text() === 'Logo símbolo'))
    expect((origin?.element as HTMLSelectElement).value).toBe('logo')
    await origin?.setValue('logo:symbol')
    expect(opened.store.get('overlays.0.src')).toBe('logo:symbol')

    await origin?.setValue('__arquivo__')
    expect(opened.store.get('overlays.0')).not.toHaveProperty('src')
    const fileInput = cards(wrapper)[0]?.findAll('input[type="text"]').find((input) => input.element.closest('.file-field'))
    expect(fileInput).toBeDefined()
    await fileInput?.setValue('C:/midia/selo.png')
    expect(opened.store.get('overlays.0.src')).toBe('C:/midia/selo.png')
  })

  it('imagem com arquivo avulso já abre em "Personalizado"', async () => {
    const opened = await openEditor(withOverlays([{ type: 'image', src: 'C:/midia/selo.png' }]))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    const origin = cards(wrapper)[0]?.findAll('select').find((select) => select.findAll('option').some((o) => o.text() === 'Logo símbolo'))
    expect((origin?.element as HTMLSelectElement).value).toBe('__arquivo__')
  })

  it('vídeo em PiP: a fonte sincronizada troca o arquivo e o rótulo do ponto de entrada', async () => {
    const opened = await openEditor(
      withOverlays([{ type: 'video', src: 'C:/midia/pip.mp4', start: 1 }], {
        sources: { palco: { src: 'C:/midia/a.mp4', sync: 0 } },
      }),
    )
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    expect(cards(wrapper)[0]?.text()).toContain('Ponto de entrada no arquivo (s)')
    const origin = cards(wrapper)[0]?.findAll('select').find((select) => select.findAll('option').some((o) => o.text() === 'palco'))
    await origin?.setValue('palco')
    expect(opened.store.get('overlays.0')).toMatchObject({ source: 'palco' })
    expect(opened.store.get('overlays.0')).not.toHaveProperty('src')
    expect(cards(wrapper)[0]?.text()).toContain('Tempo de entrada na fonte (s)')
  })

  it('trocar o tipo mantém o início e o fim', async () => {
    const opened = await openEditor(withOverlays([{ type: 'text', text: 'Oi', start: 2, end: 5 }]))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    await cards(wrapper)[0]?.find('select').setValue('image')
    expect(opened.store.get('overlays.0')).toMatchObject({ type: 'image', src: 'logo', start: 2, end: 5 })
  })

  it('sobe, desce, duplica e remove', async () => {
    const opened = await openEditor(withOverlays([{ type: 'text', text: 'A' }, { type: 'text', text: 'B' }]))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    await button(wrapper, 'Descer a sobreposição 1')?.trigger('click')
    expect((opened.store.get('overlays') as Array<{ text: string }>).map((o) => o.text)).toEqual(['B', 'A'])
    await button(wrapper, 'Duplicar a sobreposição 1')?.trigger('click')
    expect((opened.store.get('overlays') as unknown[]).length).toBe(3)
    await button(wrapper, 'Remover a sobreposição 1')?.trigger('click')
    await button(wrapper, 'Remover a sobreposição 1')?.trigger('click')
    await button(wrapper, 'Remover a sobreposição 1')?.trigger('click')
    expect(opened.store.get('overlays')).toEqual([]) // sobreposição pode acabar: ao contrário dos trechos, não há mínimo
  })

  it('audiograma e composição HTML não têm formulário: o aviso manda para a aba JSON', async () => {
    const opened = await openEditor(withOverlays([{ type: 'html', src: 'composicoes/titulo', region: 'topo' }]))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    expect(cards(wrapper)[0]?.text()).toContain('não tem formulário')
    expect(cards(wrapper)[0]?.text()).toContain('aba JSON')
    // o formulário não escreve nada por cima do que ele não conhece
    expect(opened.store.dirty).toBe(false)
  })
})

describe('OverlaysSection: a sobreposição escolhida', () => {
  const texts = [{ type: 'text', text: 'A' }, { type: 'text', text: 'B' }, { type: 'text', text: 'C' }]
  const scrollIntoView = vi.fn()

  // o jsdom não rola a tela: o método não existe nele, e o teste só confere que o cartão foi pedido
  beforeEach(() => {
    scrollIntoView.mockClear()
    Element.prototype.scrollIntoView = scrollIntoView
  })
  afterEach(() => Reflect.deleteProperty(Element.prototype, 'scrollIntoView'))

  it('o cartão da sobreposição escolhida fica marcado, e só ele', async () => {
    const opened = await openEditor(withOverlays(texts))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    expect(cards(wrapper).map((card) => card.attributes('data-selected'))).toEqual([undefined, undefined, undefined])
    opened.store.selectOverlay(1)
    await wrapper.vm.$nextTick()
    expect(cards(wrapper).map((card) => card.attributes('data-selected'))).toEqual([undefined, 'true', undefined])
  })

  it('clicar no cartão, ou focar um campo dele, escolhe a sobreposição (e a caixa dela ganha destaque no palco)', async () => {
    const opened = await openEditor(withOverlays(texts))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    await cards(wrapper)[2]?.find('.card__toggle').trigger('click')
    expect(opened.store.selectedOverlay).toBe(2)
    await cards(wrapper)[0]?.find('input').trigger('focusin')
    expect(opened.store.selectedOverlay).toBe(0)
    // escolher no inspetor não manda o inspetor se mostrar de novo
    expect(opened.store.overlayReveal).toBe(0)
  })

  it('a escolha vinda do palco abre o cartão, mesmo numa lista longa que começa recolhida, e leva o cartão à tela', async () => {
    const many = Array.from({ length: 8 }, (_, index) => ({ type: 'text', text: `T${index}` }))
    const opened = await openEditor(withOverlays(many))
    const wrapper = await mountEditorPart(OverlaysSection, opened, {}, true)
    expect(cards(wrapper)[4]?.attributes('data-expanded')).toBe('false')
    opened.store.selectOverlay(4, { reveal: true })
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(cards(wrapper)[4]?.attributes('data-expanded')).toBe('true')
    expect(cards(wrapper)[3]?.attributes('data-expanded')).toBe('false')
    expect(scrollIntoView).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('já escolhida quando o bloco aparece, a sobreposição abre na hora', async () => {
    const many = Array.from({ length: 8 }, (_, index) => ({ type: 'text', text: `T${index}` }))
    const opened = await openEditor(withOverlays(many))
    opened.store.selectOverlay(6)
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    expect(cards(wrapper)[6]?.attributes('data-expanded')).toBe('true')
  })

  it('subir ou descer leva a escolha junto, e remover a tira', async () => {
    const opened = await openEditor(withOverlays(texts))
    const wrapper = await mountEditorPart(OverlaysSection, opened)
    opened.store.selectOverlay(0)
    await button(wrapper, 'Descer a sobreposição 1')?.trigger('click')
    expect(opened.store.selectedOverlay).toBe(1)
    expect((opened.store.get('overlays') as Array<{ text: string }>)[1]?.text).toBe('A')
    await button(wrapper, 'Subir a sobreposição 2')?.trigger('click')
    expect(opened.store.selectedOverlay).toBe(0)
    await button(wrapper, 'Remover a sobreposição 1')?.trigger('click')
    expect(opened.store.selectedOverlay).toBeNull()
  })
})


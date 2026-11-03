import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useToastsStore } from '@/stores/toasts'
import { projectSpec, timelineView } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import { reply } from '@/test/routedFetch'
import JsonPanel from './JsonPanel.vue'

afterEach(() => vi.unstubAllGlobals())

type Mounted = Awaited<ReturnType<typeof mountEditorPart>>
const area = (wrapper: Mounted) => wrapper.find('textarea')
const button = (wrapper: Mounted, label: string) => wrapper.findAll('button').find((candidate) => candidate.text() === label)

describe('JsonPanel', () => {
  it('mostra a spec inteira como texto', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(JsonPanel, opened)
    const parsed = JSON.parse((area(wrapper).element as HTMLTextAreaElement).value)
    expect(parsed.name).toBe('demo')
    expect(parsed.timeline).toHaveLength(2)
    expect(button(wrapper, 'Aplicar')?.attributes('disabled')).toBeDefined()
  })

  it('aplicar passa o texto para a edição e marca "não salvo"', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(JsonPanel, opened)
    const next = { ...projectSpec(), look: 'cinema' }
    await area(wrapper).setValue(JSON.stringify(next))
    expect(button(wrapper, 'Aplicar')?.attributes('disabled')).toBeUndefined()
    await button(wrapper, 'Aplicar')?.trigger('click')
    expect(opened.store.get('look')).toBe('cinema')
    expect(opened.store.dirty).toBe(true)
    expect(useToastsStore(opened.pinia).items.at(-1)?.title).toBe('JSON aplicado')
    expect(button(wrapper, 'Aplicar')?.attributes('disabled')).toBeDefined()
  })

  it('JSON inválido mostra o erro no próprio painel e não muda a spec', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(JsonPanel, opened)
    await area(wrapper).setValue('{ "name": ')
    await button(wrapper, 'Aplicar')?.trigger('click')
    expect(wrapper.find('.json__error').text()).toContain('JSON inválido')
    expect(opened.store.dirty).toBe(false)
    expect((area(wrapper).element as HTMLTextAreaElement).value).toBe('{ "name": ') // o texto digitado fica para consertar
  })

  it('só aceita um objeto', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(JsonPanel, opened)
    await area(wrapper).setValue('[1, 2]')
    await button(wrapper, 'Aplicar')?.trigger('click')
    expect(wrapper.find('.json__error').text()).toContain('precisa ser um objeto')
  })

  it('mudança vinda dos formulários atualiza o texto, mas não sobrescreve o que a pessoa está digitando', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(JsonPanel, opened)
    opened.store.setField('output.quality', 'draft')
    await flushPromises()
    expect(JSON.parse((area(wrapper).element as HTMLTextAreaElement).value).output.quality).toBe('draft')
    await area(wrapper).setValue('texto em edição')
    opened.store.setField('output.quality', 'medium')
    await flushPromises()
    expect((area(wrapper).element as HTMLTextAreaElement).value).toBe('texto em edição')
    await button(wrapper, 'Descartar o texto digitado')?.trigger('click')
    expect(JSON.parse((area(wrapper).element as HTMLTextAreaElement).value).output.quality).toBe('medium')
  })

  it('desfazer atualiza o texto', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(JsonPanel, opened)
    opened.store.setField('output.quality', 'draft')
    opened.store.undo()
    await flushPromises()
    expect(JSON.parse((area(wrapper).element as HTMLTextAreaElement).value).output.quality).toBe('high')
  })

  it('spec inválida do disco: mostra os erros do servidor e deixa consertar, aplicar e salvar', async () => {
    const opened = await openEditor(projectSpec(), {
      'GET /api/projects/demo': reply(422, {
        detail: [{ loc: ['timeline', 0], msg: 'clipe precisa de src ou source' }],
        raw_spec: { name: 'demo', timeline: [{ type: 'clip' }], output: { preset: 'instagram/reels' } },
      }),
    })
    const wrapper = await mountEditorPart(JsonPanel, opened)
    expect(wrapper.find('.invalid').text()).toContain('não passa na validação')
    expect(wrapper.find('.invalid').text()).toContain('clipe precisa de src ou source')
    expect(JSON.parse((area(wrapper).element as HTMLTextAreaElement).value).timeline[0]).toEqual({ type: 'clip' })

    opened.fetch.set('POST /api/projects/demo/timeline', () => timelineView())
    await area(wrapper).setValue(JSON.stringify({ name: 'demo', timeline: [{ type: 'card', title: 'ok' }] }))
    await button(wrapper, 'Aplicar')?.trigger('click')
    expect(await opened.store.save()).toBe(true)
    const put = opened.fetch.to('PUT /api/projects/demo')[0]
    expect((put?.body as { timeline: unknown[] }).timeline).toEqual([{ type: 'card', title: 'ok' }])
    await flushPromises()
    expect(wrapper.find('.invalid').exists()).toBe(false)
  })
})

import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useToastsStore } from '@/stores/toasts'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import { reply } from '@/test/routedFetch'
import CaptionsPanel from './CaptionsPanel.vue'

afterEach(() => vi.unstubAllGlobals())

type Mounted = Awaited<ReturnType<typeof mountEditorPart>>
const inputs = (wrapper: Mounted) => wrapper.findAll('tbody input')

const captions = {
  language: 'pt',
  cues: [
    {
      start: 0,
      end: 1.5,
      text: 'olá mundo bonito',
      words: [
        { start: 0, end: 0.5, text: 'olá' },
        { start: 0.5, end: 1, text: 'mundo' },
        { start: 1, end: 1.5, text: 'bonito' },
      ],
    },
    { start: 65.3, end: 70, text: 'segunda frase', words: [] },
  ],
}

async function open(extra: Record<string, unknown> = {}) {
  const opened = await openEditor(undefined, { 'GET /api/projects/demo/captions': captions, ...extra })
  const wrapper = await mountEditorPart(CaptionsPanel, opened)
  return { opened, wrapper }
}

describe('CaptionsPanel', () => {
  it('mostra o início, o fim e o texto de cada frase', async () => {
    const { wrapper } = await open()
    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0]?.text()).toContain('00:00.00')
    expect(rows[1]?.text()).toContain('01:05.30')
    expect((inputs(wrapper)[0]?.element as HTMLInputElement).value).toBe('olá mundo bonito')
  })

  it('só salva depois de uma mudança, e manda o tempo das palavras refeito', async () => {
    const { opened, wrapper } = await open({ 'PUT /api/projects/demo/captions': { ok: true, cues: 2 } })
    const save = wrapper.findAll('button').find((b) => b.text() === 'Salvar legendas')
    expect(save?.attributes('disabled')).toBeDefined()
    await inputs(wrapper)[0]?.setValue('olá mundo lindo e grande')
    expect(wrapper.text()).toContain('ainda não foram salvas')
    await save?.trigger('click')
    await flushPromises()
    const sent = opened.fetch.to('PUT /api/projects/demo/captions')[0]?.body as { cues: Array<{ text: string; words: Array<{ start: number; end: number; text: string }> }> }
    expect(sent.cues[0]?.text).toBe('olá mundo lindo e grande')
    expect(sent.cues[0]?.words.map((w) => w.text)).toEqual(['olá', 'mundo', 'lindo', 'e', 'grande'])
    expect(sent.cues[0]?.words[0]?.start).toBe(0)
    expect(sent.cues[0]?.words.at(-1)?.end).toBeCloseTo(1.5, 6)
    expect(useToastsStore(opened.pinia).items.at(-1)?.title).toBe('Legendas salvas')
    expect(wrapper.text()).not.toContain('ainda não foram salvas')
  })

  it('mesmo texto não conta como mudança', async () => {
    const { wrapper } = await open()
    await inputs(wrapper)[1]?.setValue('segunda frase')
    expect(wrapper.text()).not.toContain('ainda não foram salvas')
  })

  it('erro ao carregar aparece no painel', async () => {
    const opened = await openEditor(undefined, { 'GET /api/projects/demo/captions': reply(404, { detail: 'legendas não geradas' }) })
    const wrapper = await mountEditorPart(CaptionsPanel, opened)
    expect(wrapper.find('[role="alert"]').text()).toBe('legendas não geradas')
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('erro ao salvar avisa e mantém as mudanças', async () => {
    const { opened, wrapper } = await open({ 'PUT /api/projects/demo/captions': reply(500, { detail: 'disco cheio' }) })
    await inputs(wrapper)[0]?.setValue('outro texto')
    await wrapper.findAll('button').find((b) => b.text() === 'Salvar legendas')?.trigger('click')
    await flushPromises()
    expect(useToastsStore(opened.pinia).items.at(-1)).toMatchObject({ tone: 'error', description: 'disco cheio' })
    expect(wrapper.text()).toContain('ainda não foram salvas')
  })
})

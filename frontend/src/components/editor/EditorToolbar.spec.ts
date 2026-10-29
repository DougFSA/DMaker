import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import { FakeEventSource } from '@/test/fetch'
import { reply } from '@/test/routedFetch'
import EditorToolbar from './EditorToolbar.vue'

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
})

const summary = {
  name: 'demo',
  preset: 'instagram/reels',
  resolution: '1080x1920',
  theme: 'medlycare',
  total_s: 6,
  segments: [],
  warnings: [],
}

const barButton = (label: string) =>
  wrapper?.findAll('button').find((candidate) => candidate.text() === label || candidate.attributes('aria-label') === label)
const dialogButton = (label: string) =>
  Array.from(document.body.querySelectorAll('[role="dialog"] button')).find(
    (node) => node.textContent?.trim() === label,
  ) as HTMLButtonElement | undefined

async function open(extra: Record<string, unknown> = {}) {
  // acompanhar o job abre o SSE dele
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  const opened = await openEditor(undefined, {
    'POST /api/projects/demo/validate': summary,
    'POST /api/projects/demo/render': { job_id: 'job-1' },
    'POST /api/projects/demo/export': { job_id: 'job-2' },
    ...extra,
  })
  wrapper = await mountEditorPart(EditorToolbar, opened, {}, true)
  return opened
}

describe('EditorToolbar', () => {
  it('mostra "Salvo" e desabilita desfazer e refazer enquanto nada mudou', async () => {
    await open()
    expect(wrapper?.text()).toContain('Salvo')
    expect(barButton('Desfazer')?.attributes('disabled')).toBeDefined()
    expect(barButton('Refazer')?.attributes('disabled')).toBeDefined()
  })

  it('uma mudança marca "Não salvo" e habilita o desfazer; o botão desfaz e refaz', async () => {
    const opened = await open()
    opened.store.setField('output.quality', 'draft')
    await flushPromises()
    expect(wrapper?.text()).toContain('Não salvo')
    expect(barButton('Desfazer')?.attributes('disabled')).toBeUndefined()
    await barButton('Desfazer')?.trigger('click')
    expect(opened.store.get('output.quality')).toBe('high')
    expect(wrapper?.text()).toContain('Salvo')
    await barButton('Refazer')?.trigger('click')
    expect(opened.store.get('output.quality')).toBe('draft')
  })

  it('Salvar grava a spec e volta para "Salvo"', async () => {
    const opened = await open()
    opened.store.setField('output.quality', 'draft')
    await barButton('Salvar')?.trigger('click')
    await flushPromises()
    expect(opened.fetch.to('PUT /api/projects/demo')).toHaveLength(1)
    expect(wrapper?.text()).toContain('Salvo')
  })

  it('Validar salva antes, e só então pede a validação e guarda o resultado', async () => {
    const opened = await open()
    opened.store.setField('timeline.0.speed', 2)
    await barButton('Validar')?.trigger('click')
    await flushPromises()
    const order = opened.fetch.calls
      .filter((call) => call.method !== 'GET' && !call.path.endsWith('/timeline'))
      .map((call) => `${call.method} ${call.path}`)
    expect(order).toEqual(['PUT /api/projects/demo', 'POST /api/projects/demo/validate'])
    expect(opened.store.validation?.total_s).toBe(6)
  })

  it('Validar sem mudança não salva de novo', async () => {
    const opened = await open()
    await barButton('Validar')?.trigger('click')
    await flushPromises()
    expect(opened.fetch.to('PUT /api/projects/demo')).toHaveLength(0)
    expect(opened.fetch.to('POST /api/projects/demo/validate')).toHaveLength(1)
  })

  it('se o servidor recusa a spec ao salvar, a validação não roda', async () => {
    const opened = await open({ 'PUT /api/projects/demo': reply(422, { detail: 'timeline vazia' }) })
    opened.store.setField('timeline.0.speed', 2)
    await barButton('Validar')?.trigger('click')
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/validate')).toHaveLength(0)
    expect(opened.store.validation).toBeNull()
    expect(wrapper?.text()).toContain('Não salvo')
  })

  it('Prévia abre o diálogo em modo prévia; "Só os trechos" vai no pedido, e o render é pedido depois de salvar', async () => {
    const opened = await open()
    opened.store.setField('timeline.0.speed', 2)
    await barButton('Prévia')?.trigger('click')
    await flushPromises()
    expect(document.body.querySelector('[role="dialog"]')?.textContent).toContain('Só do trecho')
    const inputs = document.body.querySelectorAll<HTMLInputElement>('#render-from, #render-to')
    inputs[0]!.value = '0'
    inputs[0]!.dispatchEvent(new Event('input'))
    inputs[1]!.value = '1'
    inputs[1]!.dispatchEvent(new Event('input'))
    dialogButton('Gerar prévia')?.click()
    await flushPromises()
    const order = opened.fetch.calls.filter((c) => c.method !== 'GET' && !c.path.endsWith('/timeline')).map((c) => `${c.method} ${c.path}`)
    expect(order).toEqual(['PUT /api/projects/demo', 'POST /api/projects/demo/render'])
    expect(opened.fetch.to('POST /api/projects/demo/render')[0]?.body).toEqual({ preview: true, segments: '0-1' })
    expect(useJobsStore(opened.pinia).forProject('demo')).toHaveLength(1)
    expect(useToastsStore(opened.pinia).items.at(-1)?.title).toBe('Render iniciado')
  })

  it('Render final abre direto no modo final e pede a versão completa', async () => {
    const opened = await open()
    await barButton('Render final')?.trigger('click')
    await flushPromises()
    expect(document.body.querySelector('[role="dialog"]')?.textContent).toContain('Qualidade completa')
    dialogButton('Renderizar')?.click()
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/render')[0]?.body).toEqual({ preview: false })
    expect(opened.fetch.to('PUT /api/projects/demo')).toHaveLength(0) // nada mudou, nada a salvar
  })

  it('Exportar pede os formatos marcados', async () => {
    const opened = await open({
      'GET /api/state': {
        presets: [{ id: 'instagram/reels', platform: 'Instagram', name: 'Reels', width: 1080, height: 1920, fps: 30 }],
        brands: [],
      },
    })
    await barButton('Exportar')?.trigger('click')
    await flushPromises()
    const box = document.body.querySelector<HTMLInputElement>('input[type="checkbox"][value="instagram/reels"]')
    box!.click()
    await flushPromises()
    dialogButton('Exportar')?.click()
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/export')[0]?.body).toEqual({ presets: ['instagram/reels'] })
  })

  it('render que não consegue salvar a spec não é pedido', async () => {
    const opened = await open({ 'PUT /api/projects/demo': reply(422, { detail: 'inválida' }) })
    opened.store.setField('timeline.0.speed', 2)
    await barButton('Render final')?.trigger('click')
    await flushPromises()
    dialogButton('Renderizar')?.click()
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/render')).toHaveLength(0)
  })
})

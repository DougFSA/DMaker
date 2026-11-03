import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useToastsStore } from '@/stores/toasts'
import { outputFile, projectDetail, projectSpec } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import { reply } from '@/test/routedFetch'
import PreviewPanel from './PreviewPanel.vue'

afterEach(() => vi.unstubAllGlobals())

type Mounted = Awaited<ReturnType<typeof mountEditorPart>>
const button = (wrapper: Mounted, label: string) => wrapper.findAll('button').find((candidate) => candidate.text() === label)

const final = outputFile({ name: 'demo__final.mp4', path: 'C:/out/demo__final.mp4', url: '/api/file?path=final', mtime: 200 })
const preview = outputFile({
  name: 'demo__preview.mp4',
  path: 'C:/out/demo__preview.mp4',
  url: '/api/file?path=preview',
  kind: 'preview',
  size_mb: 1.1,
  mtime: 300,
})

const report = {
  text: 'ok',
  project: 'demo',
  preset: 'instagram/reels',
  total: 6,
  findings: [{ level: 'aviso', where: 'saída', message: 'quadros pretos de 1.0s a 2.0s', at: 1 }],
  checks: ['zona segura'],
}

async function open(outputs = [final, preview], extra: Record<string, unknown> = {}) {
  const opened = await openEditor(projectSpec(), {
    'GET /api/projects/demo': () => projectDetail({ outputs }),
    ...extra,
  })
  const wrapper = await mountEditorPart(PreviewPanel, opened)
  return { opened, wrapper }
}

describe('PreviewPanel', () => {
  it('sem vídeo gerado, explica como gerar', async () => {
    const { wrapper } = await open([])
    expect(wrapper.text()).toContain('Nenhum vídeo gerado ainda')
    expect(wrapper.find('video').exists()).toBe(false)
  })

  it('abre no arquivo mais recente, com o tipo, o tamanho e a pasta', async () => {
    const { wrapper } = await open()
    expect(wrapper.find('video').attributes('src')).toBe('/api/file?path=preview')
    expect(wrapper.find('figcaption').text()).toContain('demo__preview.mp4')
    expect(wrapper.find('figcaption').text()).toContain('prévia')
    expect(wrapper.find('figcaption code').text()).toBe('C:/out')
  })

  it('deixa escolher outro arquivo e troca o vídeo', async () => {
    const { wrapper } = await open()
    const options = wrapper.findAll('option').map((o) => o.text())
    expect(options[0]).toContain('demo__preview.mp4 · prévia')
    expect(options[1]).toContain('demo__final.mp4 · final')
    await wrapper.find('select').setValue('C:/out/demo__final.mp4')
    expect(wrapper.find('video').attributes('src')).toBe('/api/file?path=final')
  })

  it('o relatório de QA confere o arquivo escolhido (output), com o aviso da prévia', async () => {
    const { opened, wrapper } = await open([preview], { 'POST /api/projects/demo/qa': report })
    expect(wrapper.text()).toContain('A prévia é menor que a versão final')
    await button(wrapper, 'Relatório de QA')?.trigger('click')
    await flushPromises()
    const call = opened.fetch.to('POST /api/projects/demo/qa')[0]
    expect(call?.body).toEqual({ output: 'C:/out/demo__preview.mp4' })
    expect(wrapper.text()).toContain('quadros pretos de 1.0s a 2.0s')
  })

  it('trocar de arquivo limpa o que foi conferido do anterior', async () => {
    const { wrapper } = await open([final, preview], { 'POST /api/projects/demo/qa': report })
    await button(wrapper, 'Relatório de QA')?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Conferência de qualidade')
    await wrapper.find('select').setValue('C:/out/demo__final.mp4')
    expect(wrapper.text()).not.toContain('Conferência de qualidade')
  })

  it('a grade de quadros mostra a imagem do servidor', async () => {
    const { opened, wrapper } = await open([final], {
      'POST /api/qa/sheet': { image: 'C:/out/demo_sheet.png', url: '/api/file?path=sheet' },
    })
    await button(wrapper, 'Grade de quadros')?.trigger('click')
    await flushPromises()
    expect(opened.fetch.to('POST /api/qa/sheet')[0]?.body).toEqual({ video: final.path })
    const image = wrapper.find('img[alt="Grade de quadros do vídeo"]')
    expect(image.attributes('src')).toContain('/api/file?path=sheet')
  })

  it('o quadro em t pede o instante digitado', async () => {
    const { opened, wrapper } = await open([final], {
      'POST /api/qa/frame': { image: 'C:/out/f.jpg', url: '/api/file?path=frame', t: 2.5 },
    })
    await wrapper.find('input[type="number"]').setValue('2.5')
    await button(wrapper, 'Ver o quadro')?.trigger('click')
    await flushPromises()
    expect(opened.fetch.to('POST /api/qa/frame')[0]?.body).toEqual({ video: final.path, t: 2.5 })
    expect(wrapper.find('img[alt="Quadro do vídeo no instante pedido"]').exists()).toBe(true)
  })

  it('erro do servidor vira aviso', async () => {
    const { opened, wrapper } = await open([final], { 'POST /api/qa/sheet': reply(404, { detail: 'vídeo não encontrado' }) })
    await button(wrapper, 'Grade de quadros')?.trigger('click')
    await flushPromises()
    expect(useToastsStore(opened.pinia).items.at(-1)).toMatchObject({ tone: 'error', description: 'vídeo não encontrado' })
    expect(wrapper.find('img').exists()).toBe(false)
  })
})

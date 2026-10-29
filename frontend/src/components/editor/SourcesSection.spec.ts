import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useToastsStore } from '@/stores/toasts'
import { projectSpec } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import { reply } from '@/test/routedFetch'
import SourcesSection from './SourcesSection.vue'

afterEach(() => vi.unstubAllGlobals())

type Mounted = Awaited<ReturnType<typeof mountEditorPart>>
const button = (wrapper: Mounted, label: string) =>
  wrapper.findAll('button').find((candidate) => candidate.attributes('aria-label') === label || candidate.text() === label)

function multicam(): Record<string, unknown> {
  return {
    ...projectSpec(),
    master: 'palco',
    sources: {
      palco: { src: 'C:/midia/a.mp4', sync: 0 },
      mesa: { src: 'C:/midia/mesa.wav', sync: 'auto', audio_stream: 1, label: 'Mesa' },
    },
    timeline: [
      { type: 'clip', source: 'mesa', start: 0, end: 3 },
      { type: 'clip', src: 'c.mp4', start: 0, end: 2 },
    ],
    overlays: [{ type: 'video', source: 'mesa', start: 0 }],
    audio: { tracks: [{ source: 'mesa', volume: 0.5 }] },
  }
}

describe('SourcesSection', () => {
  it('sem fontes, explica para que servem e só oferece adicionar', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SourcesSection, opened)
    expect(wrapper.text()).toContain('Nenhuma fonte sincronizada ainda')
    expect(button(wrapper, 'Sincronizar agora')?.attributes('disabled')).toBeDefined()
  })

  it('adiciona uma fonte automática com nome livre', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SourcesSection, opened)
    await button(wrapper, 'Adicionar fonte')?.trigger('click')
    await button(wrapper, 'Adicionar fonte')?.trigger('click')
    expect(Object.keys(opened.store.get('sources') as object)).toEqual(['fonte1', 'fonte2'])
    expect(opened.store.get('sources.fonte1')).toEqual({ src: '', sync: 'auto', audio_stream: 0 })
  })

  it('mostra cada fonte com o arquivo, o modo de sincronização e os campos próprios', async () => {
    const opened = await openEditor(multicam())
    const wrapper = await mountEditorPart(SourcesSection, opened)
    const rows = wrapper.findAll('li.row')
    expect(rows).toHaveLength(2)
    expect(rows[0]?.text()).toContain('Deslocamento (s)') // palco: manual (sync 0)
    expect(rows[1]?.text()).not.toContain('Deslocamento (s)') // mesa: automática
    const labels = rows[1]?.findAll('input').map((input) => (input.element as HTMLInputElement).value)
    expect(labels).toContain('Mesa')
    expect(labels).toContain('C:/midia/mesa.wav')
  })

  it('renomear só vale ao sair do campo e leva junto todas as referências', async () => {
    const opened = await openEditor(multicam())
    const wrapper = await mountEditorPart(SourcesSection, opened)
    const name = wrapper.findAll('li.row')[1]?.find('input[type="text"]')
    // digitar dispara só `input`; o `change` vem ao sair do campo (o setValue do test-utils dispara os dois)
    ;(name?.element as HTMLInputElement).value = 'mesa do dj'
    await name?.trigger('input')
    expect(Object.keys(opened.store.get('sources') as object)).toEqual(['palco', 'mesa']) // ainda não
    await name?.trigger('change')
    expect(Object.keys(opened.store.get('sources') as object)).toEqual(['palco', 'mesa-do-dj'])
    expect(opened.store.get('timeline.0.source')).toBe('mesa-do-dj')
    expect(opened.store.get('overlays.0.source')).toBe('mesa-do-dj')
    expect(opened.store.get('audio.tracks.0.source')).toBe('mesa-do-dj')
  })

  it('nome já usado avisa e não troca nada', async () => {
    const opened = await openEditor(multicam())
    const wrapper = await mountEditorPart(SourcesSection, opened)
    const name = wrapper.findAll('li.row')[1]?.find('input[type="text"]')
    await name?.setValue('palco') // dispara input e change
    expect(Object.keys(opened.store.get('sources') as object)).toEqual(['palco', 'mesa'])
    expect(Object.keys(opened.store.get('sources') as object)).toEqual(['palco', 'mesa'])
    expect(useToastsStore(opened.pinia).items.at(-1)?.title).toContain('Já existe uma fonte')
  })

  it('remover deixa os clipes dessa fonte sem origem e tira as faixas dela', async () => {
    const opened = await openEditor(multicam())
    const wrapper = await mountEditorPart(SourcesSection, opened)
    await button(wrapper, 'Remover a fonte mesa')?.trigger('click')
    expect(Object.keys(opened.store.get('sources') as object)).toEqual(['palco'])
    expect(opened.store.get('timeline.0')).not.toHaveProperty('source')
    expect(opened.store.get('audio.tracks')).toEqual([])
  })

  it('trocar para sincronização manual guarda um deslocamento numérico', async () => {
    const opened = await openEditor(multicam())
    const wrapper = await mountEditorPart(SourcesSection, opened)
    const mode = wrapper.findAll('li.row')[1]?.findAll('select').find((select) => select.findAll('option').some((o) => o.text().startsWith('Manual')))
    await mode?.setValue('manual')
    expect(opened.store.get('sources.mesa.sync')).toBe(0)
    expect(wrapper.findAll('li.row')[1]?.text()).toContain('Deslocamento (s)')
  })

  it('a fonte principal troca por nome, e "Automática" limpa o campo', async () => {
    const opened = await openEditor(multicam())
    const wrapper = await mountEditorPart(SourcesSection, opened)
    const master = wrapper.find('.master select')
    expect(master.findAll('option').map((o) => o.text())).toEqual(['Automática (palco)', 'palco', 'mesa'])
    await master.setValue('mesa')
    expect(opened.store.get('master')).toBe('mesa')
    await master.setValue('')
    expect(opened.store.spec).not.toHaveProperty('master')
  })

  it('fonte em partes mostra o aviso em vez do campo de arquivo', async () => {
    const spec = { ...projectSpec(), sources: { camera: { parts: ['a.mp4', 'b.mp4'], sync: 0 } } }
    const opened = await openEditor(spec)
    const wrapper = await mountEditorPart(SourcesSection, opened)
    expect(wrapper.text()).toContain('2 arquivos em sequência')
    expect(wrapper.text()).toContain('aba JSON')
  })

  describe('Sincronizar agora', () => {
    it('mede contra a principal, mostra a tabela e "Usar estes valores" grava o deslocamento', async () => {
      const opened = await openEditor(multicam(), {
        'POST /api/sync': [{ path: 'C:/midia/mesa.wav', offset_s: 1.234, confidence: 0.91, reliable: true }],
      })
      const wrapper = await mountEditorPart(SourcesSection, opened)
      await button(wrapper, 'Sincronizar agora')?.trigger('click')
      await flushPromises()
      const call = opened.fetch.to('POST /api/sync')[0]
      expect(call?.body).toEqual({ master: 'C:/midia/a.mp4', others: ['C:/midia/mesa.wav'], master_stream: 0 })
      const row = wrapper.find('tbody tr')
      expect(row.text()).toContain('mesa.wav')
      expect(row.text()).toContain('1.234')
      expect(row.text()).toContain('91%')
      expect(row.text()).toContain('Sim')
      await button(wrapper, 'Usar estes valores')?.trigger('click')
      expect(opened.store.get('sources.mesa.sync')).toBe(1.234)
      expect(wrapper.find('tbody tr').exists()).toBe(false)
    })

    it('fonte sem arquivo não chama o servidor e avisa', async () => {
      const spec = multicam()
      ;(spec.sources as Record<string, Record<string, unknown>>).mesa!.src = ''
      const opened = await openEditor(spec)
      const wrapper = await mountEditorPart(SourcesSection, opened)
      await button(wrapper, 'Sincronizar agora')?.trigger('click')
      expect(opened.fetch.to('POST /api/sync')).toHaveLength(0)
      expect(useToastsStore(opened.pinia).items.at(-1)?.title).toContain('Preencha o arquivo')
    })

    it('erro do servidor vira aviso e não deixa tabela', async () => {
      const opened = await openEditor(multicam(), { 'POST /api/sync': reply(400, { detail: 'sem áudio para comparar' }) })
      const wrapper = await mountEditorPart(SourcesSection, opened)
      await button(wrapper, 'Sincronizar agora')?.trigger('click')
      await flushPromises()
      expect(wrapper.find('tbody').exists()).toBe(false)
      expect(useToastsStore(opened.pinia).items.at(-1)).toMatchObject({ tone: 'error', description: 'sem áudio para comparar' })
    })
  })
})

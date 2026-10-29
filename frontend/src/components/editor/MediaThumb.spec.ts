import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { TimelineView } from '@/api'
import { projectSpec, timelineItem, timelineTrack, timelineView } from '@/test/editorFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { reply } from '@/test/routedFetch'
import MediaThumb from './MediaThumb.vue'

let wrapper: VueWrapper | null = null

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

/** Um projeto cujos trechos usam arquivos relativos à pasta do projeto: o servidor resolve cada um na vista. */
function relativeView(extra: Partial<TimelineView> = {}): TimelineView {
  return {
    ...timelineView(),
    tracks: [
      timelineTrack('V1', [
        timelineItem(0, { src: 'cam2.mp4', path: 'C:/projetos/demo/cam2.mp4' }),
        timelineItem(1, { src: 'perdido.mp4', path: 'C:/projetos/demo/perdido.mp4', missing: true }),
      ]),
    ],
    ...extra,
  }
}

async function mountThumb(props: { src: string; kind: 'video' | 'image' }, routes: Record<string, unknown> = {}): Promise<{ panel: VueWrapper; opened: OpenedEditor }> {
  const opened = await openEditor(projectSpec(), { 'POST /api/projects/demo/timeline': () => relativeView(), ...routes })
  wrapper = await mountEditorPart(MediaThumb, opened, props)
  return { panel: wrapper, opened }
}

describe('MediaThumb', () => {
  it('um arquivo de caminho absoluto aparece na hora, pela rota de arquivos', async () => {
    const { panel } = await mountThumb({ src: 'C:/midia/foto.png', kind: 'image' })
    expect(panel.find('img').attributes('src')).toBe('/api/file?path=C%3A%2Fmidia%2Ffoto.png')
  })

  it('o vídeo mostra o primeiro quadro sem tocar', async () => {
    const { panel } = await mountThumb({ src: 'C:/midia/cena.mp4', kind: 'video' })
    const video = panel.find('video')
    expect(video.attributes('src')).toBe('/api/file?path=C%3A%2Fmidia%2Fcena.mp4#t=0.1')
    expect(video.attributes('preload')).toBe('metadata')
  })

  it('arquivo relativo usa o caminho que a vista resolveu, e nunca pede o caminho cru ao servidor', async () => {
    const { panel } = await mountThumb({ src: 'cam2.mp4', kind: 'video' })
    expect(panel.find('video').attributes('src')).toBe('/api/file?path=C%3A%2Fprojetos%2Fdemo%2Fcam2.mp4#t=0.1')
    expect(panel.html()).not.toContain('path=cam2.mp4')
  })

  it('enquanto a vista não chegou, o arquivo relativo espera em vez de pedir um caminho que dá 404', async () => {
    // a vista demora (spec ainda calculando): a miniatura não tem como saber o caminho absoluto
    const { panel } = await mountThumb({ src: 'cam2.mp4', kind: 'video' }, { 'POST /api/projects/demo/timeline': reply(422, { detail: 'ainda calculando' }) })
    expect(panel.find('video').exists()).toBe(false)
    expect(panel.find('img').exists()).toBe(false)
    expect(panel.html()).not.toContain('/api/file')
  })

  it('o arquivo relativo aparece quando a vista chega, mesmo se antes ele esperou', async () => {
    const { panel, opened } = await mountThumb({ src: 'cam2.mp4', kind: 'video' }, { 'POST /api/projects/demo/timeline': reply(422, { detail: 'ainda calculando' }) })
    expect(panel.find('video').exists()).toBe(false)
    opened.fetch.set('POST /api/projects/demo/timeline', () => relativeView())
    await opened.store.refreshView()
    await flushPromises()
    expect(panel.find('video').attributes('src')).toContain('C%3A%2Fprojetos%2Fdemo%2Fcam2.mp4')
  })

  it('arquivo que a vista marcou como ausente mostra o aviso e não pede nada ao servidor', async () => {
    const { panel, opened } = await mountThumb({ src: 'perdido.mp4', kind: 'video' })
    expect(panel.find('video').exists()).toBe(false)
    expect(panel.find('[role="img"]').attributes('aria-label')).toBe('Arquivo não encontrado')
    expect(panel.text()).toContain('Arquivo não encontrado')
    expect(opened.fetch.calls.filter((call) => call.path === '/api/file')).toHaveLength(0)
  })

  it('áudio não tem quadro: nada aparece', async () => {
    const { panel } = await mountThumb({ src: 'C:/midia/musica.mp3', kind: 'video' })
    expect(panel.find('video').exists()).toBe(false)
    expect(panel.find('.thumb').exists()).toBe(false)
  })

  it('sem arquivo escolhido, nada aparece', async () => {
    const { panel } = await mountThumb({ src: '', kind: 'image' })
    expect(panel.find('.thumb').exists()).toBe(false)
  })

  it('se o navegador não abre o arquivo, a miniatura some, e tenta de novo quando o endereço muda', async () => {
    const { panel } = await mountThumb({ src: 'C:/midia/foto.png', kind: 'image' })
    await panel.find('img').trigger('error')
    expect(panel.find('img').exists()).toBe(false)
    await panel.setProps({ src: 'C:/midia/outra.png' })
    expect(panel.find('img').attributes('src')).toBe('/api/file?path=C%3A%2Fmidia%2Foutra.png')
  })
})

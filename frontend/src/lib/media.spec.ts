import { describe, expect, it } from 'vitest'
import type { TimelineView } from '@/api'
import {
  collectMediaEntries,
  hasRelativePaths,
  projectMediaOptions,
  replaceSourceOps,
  type MediaEntry,
  type MediaSpec,
} from './media'

const spec: MediaSpec = {
  sources: { cam1: { src: 'D:/m/cam1.mp4' }, cam2: { parts: ['D:/m/cam2a.mp4', 'D:/m/cam2b.mp4'] } },
  timeline: [
    { type: 'clip', src: 'a.mp4' },
    { type: 'card' },
    { type: 'image', src: 'foto.png' },
    { type: 'clip', src: 'a.mp4' },
  ],
  overlays: [
    { type: 'video', src: 'b.mp4' },
    { type: 'image', src: 'logo' },
    { type: 'image', src: 'logo:escuro' },
    { type: 'image', src: 'selo.png' },
    { type: 'text' },
  ],
  audio: { music: { src: 'musica.mp3' } },
}

function view(paths: Record<string, string>, sources: TimelineView['sources'] = {}): TimelineView {
  return {
    total: 10,
    fps: 30,
    width: 1080,
    height: 1920,
    warnings: [],
    sources,
    tracks: [
      {
        id: 'V1',
        kind: 'video',
        label: 'V1',
        muted: false,
        hidden: false,
        locked: false,
        items: Object.entries(paths).map(([src, path], index) => ({
          id: `V1-${index}`,
          kind: 'clip',
          index,
          label: src,
          start: 0,
          end: 1,
          in_point: 0,
          out_point: null,
          src,
          source: null,
          transition: null,
          muted: false,
          extra: {},
          path,
        })),
      },
    ],
  }
}

describe('collectMediaEntries', () => {
  it('lista fontes e arquivos avulsos sem repetir nem contar logo', () => {
    const entries = collectMediaEntries(spec)
    expect(entries.map((entry) => [entry.id, entry.kind, entry.label])).toEqual([
      ['source:cam1', 'clip', 'cam1'],
      ['source:cam2', 'clip', 'cam2'],
      ['file:a.mp4', 'clip', 'a.mp4'],
      ['file:foto.png', 'image', 'foto.png'],
      ['file:b.mp4', 'clip', 'b.mp4'],
      ['file:selo.png', 'image', 'selo.png'],
      ['file:musica.mp3', 'audio', 'musica.mp3'],
    ])
  })

  it('a fonte usa o primeiro arquivo das partes quando não tem src', () => {
    expect(collectMediaEntries(spec).find((entry) => entry.source === 'cam2')?.path).toBe('D:/m/cam2a.mp4')
  })

  it('um arquivo que já é fonte sincronizada não aparece de novo como avulso', () => {
    const entries = collectMediaEntries({
      sources: { cam1: { src: 'cam1.mp4' } },
      timeline: [{ type: 'clip', src: 'cam1.mp4' }],
    })
    expect(entries.map((entry) => entry.id)).toEqual(['source:cam1'])
  })

  it('troca o caminho relativo pelo absoluto que o servidor resolveu', () => {
    const entries = collectMediaEntries(
      { timeline: [{ type: 'clip', src: 'a.mp4' }], sources: { cam1: { src: 'c1.mp4' } } },
      view({ 'a.mp4': 'X:/projetos/demo/a.mp4' }, { cam1: { src: 'c1.mp4', parts: [], offset: 0, in_point: 0, path: 'X:/projetos/demo/c1.mp4' } }),
    )
    expect(entries.find((entry) => entry.source === 'cam1')?.path).toBe('X:/projetos/demo/c1.mp4')
    const clip = entries.find((entry) => entry.src === 'a.mp4')
    expect(clip).toMatchObject({ path: 'X:/projetos/demo/a.mp4', src: 'a.mp4' })
  })

  it('spec vazia não dá entrada', () => {
    expect(collectMediaEntries({})).toEqual([])
  })
})

describe('hasRelativePaths', () => {
  const entry = (path: string): MediaEntry => ({ id: path, kind: 'clip', label: path, path })

  it('reconhece caminho absoluto do Windows, UNC e POSIX', () => {
    expect(hasRelativePaths([entry('D:/a.mp4'), entry('C:\\v\\b.mp4'), entry('\\\\srv\\c.mp4'), entry('/mnt/d.mp4')])).toBe(false)
  })

  it('basta um relativo', () => {
    expect(hasRelativePaths([entry('D:/a.mp4'), entry('cards/abertura.png')])).toBe(true)
  })
})

describe('projectMediaOptions', () => {
  it('só lista vídeo e áudio com caminho, numerando as opções', () => {
    const entries: MediaEntry[] = [
      { id: '1', kind: 'clip', label: 'a.mp4', path: 'D:/a.mp4', src: 'a.mp4' },
      { id: '2', kind: 'image', label: 'f.png', path: 'D:/f.png' },
      { id: '3', kind: 'audio', label: 'm.mp3', path: 'D:/m.mp3', src: 'm.mp3' },
      { id: '4', kind: 'clip', label: 'x', path: '' },
    ]
    expect(projectMediaOptions(entries).map((option) => [option.value, option.label, option.path])).toEqual([
      ['project:0', 'a.mp4', 'D:/a.mp4'],
      ['project:1', 'm.mp3', 'D:/m.mp3'],
    ])
  })
})

describe('replaceSourceOps', () => {
  const replaceSpec: MediaSpec = {
    timeline: [
      { type: 'clip', src: 'a.mp4' },
      { type: 'card' },
      { type: 'clip', src: 'b.mp4' },
      { type: 'clip', src: 'a.mp4' },
    ],
    overlays: [
      { type: 'video', src: 'a.mp4' },
      { type: 'image', src: 'a.mp4' },
    ],
  }

  it('troca o arquivo nos trechos de vídeo e nos vídeos sobrepostos que o usam', () => {
    const entry: MediaEntry = { id: 'file:a.mp4', kind: 'clip', label: 'a.mp4', path: 'D:/a.mp4', src: 'a.mp4' }
    const ops = replaceSourceOps(replaceSpec, entry, 'out/c.mp4')
    expect(ops.map((op) => op.path)).toEqual(['timeline.0.src', 'timeline.3.src', 'overlays.0.src'])
    expect(ops.every((op) => op.type === 'set_field' && op.value === 'out/c.mp4')).toBe(true)
  })

  it('numa fonte sincronizada troca só o src dela', () => {
    const entry: MediaEntry = { id: 'source:cam1', kind: 'clip', label: 'cam1', path: 'D:/c.mp4', source: 'cam1' }
    expect(replaceSourceOps(replaceSpec, entry, 'out/c.mp4')).toEqual([
      { type: 'set_field', path: 'sources.cam1.src', value: 'out/c.mp4' },
    ])
  })

  it('sem entrada ou sem spec não há o que trocar', () => {
    expect(replaceSourceOps(replaceSpec, null, 'x')).toEqual([])
    expect(replaceSourceOps(null, { id: 'f', kind: 'clip', label: 'a', path: 'a', src: 'a' }, 'x')).toEqual([])
  })

  it('um arquivo que nenhum trecho usa não gera operação', () => {
    const entry: MediaEntry = { id: 'file:z.mp4', kind: 'clip', label: 'z.mp4', path: 'z.mp4', src: 'z.mp4' }
    expect(replaceSourceOps(replaceSpec, entry, 'x')).toEqual([])
  })
})

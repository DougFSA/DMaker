import { describe, expect, it } from 'vitest'
import type { TimelineItem, TimelineView } from '@/api'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import { filterSchema } from '@/test/filterFixtures'
import { getPath } from './editorPaths'
import { FILTER_CATALOG, groupsFor } from './filterCatalog'
import {
  contextKey,
  defaultAt,
  defaultsDefOf,
  isGroupApplied,
  isPinned,
  resetPaths,
  resetPathsIn,
  selectionFor,
  targetTitle,
} from './filters'

const schema = filterSchema()
const group = (id: string) => FILTER_CATALOG.find((candidate) => candidate.id === id)!

function viewWith(tracks: Array<[string, Array<Partial<TimelineItem>>]>): TimelineView {
  return {
    total: 20,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: tracks.map(([id, items]) => timelineTrack(id, items.map((extra, index) => timelineItem(index, { id: `${id}-${index}`, ...extra })))),
    sources: {},
    warnings: [],
  }
}

describe('selectionFor: do item da linha do tempo ao tipo de filtros', () => {
  const view = viewWith([
    ['V1', [{ kind: 'clip' }, { kind: 'image' }, { kind: 'card' }]],
    ['A1', [{ kind: 'audio' }, { kind: 'audio', index: 2 }]],
  ])
  const item = (index: number, kind = 'clip') => ({ index, kind })

  it('os trechos da V1 são do tipo do próprio item, no índice dele da spec', () => {
    expect(selectionFor('V1', item(0, 'clip'), view)).toEqual({ target: 'clip', base: 'timeline.0' })
    expect(selectionFor('V1', item(1, 'image'), view)).toEqual({ target: 'image', base: 'timeline.1' })
    expect(selectionFor('V1', item(2, 'card'), view)).toEqual({ target: 'card', base: 'timeline.2' })
  })

  it('a A1 edita o clipe da V1 de mesmo índice', () => {
    expect(selectionFor('A1', item(0, 'audio'), view)).toEqual({ target: 'clip', base: 'timeline.0' })
    // o terceiro trecho é um cartão, e o item da A1 que aponta para ele edita o cartão
    expect(selectionFor('A1', item(2, 'audio'), view)).toEqual({ target: 'card', base: 'timeline.2' })
  })

  it('item da A1 sem trecho correspondente na V1 cai nos filtros do projeto', () => {
    expect(selectionFor('A1', item(9, 'audio'), view)).toBeNull()
  })

  it('as sobreposições vão para overlays, cada trilha com o seu tipo', () => {
    expect(selectionFor('TX', item(3, 'text'), view)).toEqual({ target: 'text', base: 'overlays.3' })
    expect(selectionFor('GR', item(1, 'image'), view)).toEqual({ target: 'image-overlay', base: 'overlays.1' })
    expect(selectionFor('GR', item(0, 'progress-bar'), view)).toEqual({ target: 'progress-bar', base: 'overlays.0' })
    expect(selectionFor('V2', item(2, 'video'), view)).toEqual({ target: 'video', base: 'overlays.2' })
    expect(selectionFor('V3', item(0, 'video'), view)).toEqual({ target: 'video', base: 'overlays.0' })
  })

  it('o áudio vai para audio: faixas externas, música e as legendas', () => {
    expect(selectionFor('A2', item(0, 'audio'), view)).toEqual({ target: 'track', base: 'audio.tracks.0' })
    expect(selectionFor('A3', item(1, 'audio'), view)).toEqual({ target: 'track', base: 'audio.tracks.1' })
    expect(selectionFor('MUS', item(0, 'music'), view)).toEqual({ target: 'music', base: 'audio.music' })
    expect(selectionFor('CC', item(0, 'caption'), view)).toEqual({ target: 'captions', base: 'captions' })
  })

  it('a narração e o que o catálogo não conhece não têm filtros próprios', () => {
    expect(selectionFor('NAR', item(0, 'narration'), view)).toBeNull()
    expect(selectionFor('V1', item(0, 'hologram'), view)).toBeNull()
    expect(selectionFor('XYZ', item(0), view)).toBeNull()
  })

  it('a chave muda com a seleção e vale "project" sem ela', () => {
    expect(contextKey(null)).toBe('project')
    expect(contextKey({ target: 'clip', base: 'timeline.1' })).toBe('clip:timeline.1')
    expect(contextKey({ target: 'clip', base: 'timeline.1' })).not.toBe(contextKey({ target: 'clip', base: 'timeline.2' }))
  })

  it('o título do painel diz o tipo', () => {
    expect(targetTitle('clip')).toBe('Clipe')
    expect(targetTitle('video')).toBe('Vídeo (PiP)')
    expect(targetTitle('project')).toBe('Projeto (nada selecionado)')
  })
})

describe('defaultAt: os padrões vêm do schema', () => {
  it('lê um campo direto e um aninhado dentro do padrão do contêiner', () => {
    expect(defaultAt(schema, 'ClipSegment', 'speed')).toBe(1)
    expect(defaultAt(schema, 'ClipSegment', 'reframe.zoom')).toBe(1)
    expect(defaultAt(schema, 'ClipSegment', 'reframe.focus.1')).toBe(0.5)
    expect(defaultAt(schema, 'ClipSegment', 'color.brightness')).toBe(0)
  })

  it('contêiner opcional sem padrão (a transição) não tem padrão para os campos de dentro', () => {
    expect(defaultAt(schema, 'ClipSegment', 'transition')).toBeNull()
    expect(defaultAt(schema, 'ClipSegment', 'transition.type')).toBeUndefined()
  })

  it('campo obrigatório, definição ou schema desconhecidos não têm padrão', () => {
    expect(defaultAt(schema, 'Music', 'src')).toBeUndefined()
    expect(defaultAt(schema, 'Inexistente', 'speed')).toBeUndefined()
    expect(defaultAt(null, 'ClipSegment', 'speed')).toBeUndefined()
    expect(defaultAt(schema, null, 'speed')).toBeUndefined()
  })
})

describe('isGroupApplied', () => {
  const clip = (extra: Record<string, unknown> = {}) => ({ type: 'clip', speed: 1, reframe: { mode: 'auto', zoom: 1 }, ...extra })
  const readFrom = (item: Record<string, unknown>) => (path: string) => getPath(item, path)

  it('com tudo no padrão (ou ausente) o grupo não está aplicado', () => {
    expect(isGroupApplied(group('reframe'), 'ClipSegment', schema, readFrom(clip()))).toBe(false)
    expect(isGroupApplied(group('speed'), 'ClipSegment', schema, readFrom(clip()))).toBe(false)
    expect(isGroupApplied(group('color'), 'ClipSegment', schema, readFrom(clip()))).toBe(false)
  })

  it('um campo fora do padrão aplica o grupo inteiro', () => {
    expect(isGroupApplied(group('speed'), 'ClipSegment', schema, readFrom(clip({ speed: 2 })))).toBe(true)
    expect(isGroupApplied(group('reframe'), 'ClipSegment', schema, readFrom(clip({ reframe: { mode: 'crop' } })))).toBe(true)
    expect(isGroupApplied(group('reframe'), 'ClipSegment', schema, readFrom(clip({ reframe: { focus: [0.2, 0.5] } })))).toBe(true)
  })

  it('null e ausente são a mesma coisa', () => {
    expect(isGroupApplied(group('label'), 'ClipSegment', schema, readFrom(clip({ label: null })))).toBe(false)
    expect(isGroupApplied(group('label'), 'ClipSegment', schema, readFrom(clip({ label: 'abertura' })))).toBe(true)
  })

  it('uma transição que existe aplica o grupo, mesmo com os valores do servidor', () => {
    expect(isGroupApplied(group('transition'), 'ClipSegment', schema, readFrom(clip()))).toBe(false)
    expect(isGroupApplied(group('transition'), 'ClipSegment', schema, readFrom(clip({ transition: { type: 'fade', duration: 0.5 } })))).toBe(true)
  })

  it('grupo com campo obrigatório está sempre aplicado (a música, o texto)', () => {
    expect(isGroupApplied(group('music-main'), 'Music', schema, () => undefined)).toBe(true)
    expect(isGroupApplied(group('text-content'), 'TextOverlay', schema, () => undefined)).toBe(true)
    expect(isPinned(group('music-main'), 'Music', schema)).toBe(true)
    expect(isPinned(group('music-fade'), 'Music', schema)).toBe(false)
  })

  it('sem o schema nada se sabe do padrão: o que a spec tem conta como aplicado', () => {
    expect(isGroupApplied(group('speed'), 'ClipSegment', null, readFrom(clip()))).toBe(true)
    expect(isGroupApplied(group('speed'), 'ClipSegment', null, () => undefined)).toBe(false)
  })

  it('os grupos do projeto usam a definição própria, não a do item', () => {
    expect(defaultsDefOf(group('project-output'), 'project')).toBe('Output')
    expect(defaultsDefOf(group('speed'), 'clip')).toBe('ClipSegment')
    const output = { preset: 'instagram/reels', quality: 'high', encoder: 'x264', guides: false }
    expect(isGroupApplied(group('project-output'), 'Output', schema, readFrom(output))).toBe(false)
    expect(isGroupApplied(group('project-output'), 'Output', schema, readFrom({ ...output, guides: true }))).toBe(true)
  })

  it('todo grupo do clipe é decidível com o schema (nenhum erro nos campos aninhados)', () => {
    for (const candidate of groupsFor('clip')) {
      expect(() => isGroupApplied(candidate, 'ClipSegment', schema, () => undefined), candidate.id).not.toThrow()
    }
  })
})

describe('resetPaths e resetPathsIn: o "×" de um grupo', () => {
  it('apaga o contêiner de cada campo (reframe inteiro, não campo a campo)', () => {
    expect(resetPaths(group('reframe'), 'timeline.2', 'ClipSegment', schema)).toEqual(['timeline.2.reframe'])
    expect(resetPaths(group('fade'), 'timeline.2', 'ClipSegment', schema)).toEqual(['timeline.2.fade_in', 'timeline.2.fade_out'])
    expect(resetPaths(group('text-style'), 'overlays.0', 'TextOverlay', schema)).toEqual(['overlays.0.style'])
  })

  it('o campo obrigatório fica, para a spec não ficar inválida', () => {
    expect(resetPaths(group('music-main'), 'audio.music', 'Music', schema)).not.toContain('audio.music.src')
    expect(resetPaths(group('music-main'), 'audio.music', 'Music', schema)).toContain('audio.music.volume')
    expect(resetPaths(group('text-content'), 'overlays.0', 'TextOverlay', schema)).toEqual(['overlays.0.secondary', 'overlays.0.role'])
  })

  it('apaga da spec e não inventa caminho que não existia', () => {
    const spec: Record<string, unknown> = { timeline: [{ type: 'clip', speed: 2, reframe: { zoom: 2 } }] }
    resetPathsIn(spec, ['timeline.0.reframe', 'timeline.0.speed', 'timeline.0.transition', 'overlays.4.style'])
    expect(spec).toEqual({ timeline: [{ type: 'clip' }] })
  })
})

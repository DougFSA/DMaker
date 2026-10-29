import { describe, expect, it } from 'vitest'
import { cloneJson, getPath, isAbsolutePath, pruneEmpty, setPath } from './editorPaths'

describe('getPath', () => {
  const spec = { timeline: [{ reframe: { focus: [0.2, 0.8] } }], output: { fps: 0 } }

  it('segue objetos e índices de lista', () => {
    expect(getPath(spec, 'timeline.0.reframe.focus.1')).toBe(0.8)
    expect(getPath(spec, 'output.fps')).toBe(0)
  })

  it('devolve undefined quando algum trecho do caminho não existe', () => {
    expect(getPath(spec, 'timeline.3.src')).toBeUndefined()
    expect(getPath(spec, 'audio.music.src')).toBeUndefined()
    expect(getPath(null, 'a')).toBeUndefined()
  })

  it('não segue chaves do protótipo', () => {
    expect(getPath(spec, '__proto__')).toBeUndefined()
    expect(getPath(spec, 'timeline.constructor')).toBeUndefined()
  })
})

describe('setPath', () => {
  it('cria objetos e listas que faltam pelo caminho', () => {
    const spec: Record<string, unknown> = {}
    setPath(spec, 'audio.music.src', 'a.mp3')
    setPath(spec, 'timeline.0.reframe.focus.1', 0.4)
    expect(spec).toEqual({ audio: { music: { src: 'a.mp3' } }, timeline: [{ reframe: { focus: [undefined, 0.4] } }] })
    expect(Array.isArray(getPath(spec, 'timeline'))).toBe(true)
  })

  it('troca o valor que já existe', () => {
    const spec: Record<string, unknown> = { output: { quality: 'high' } }
    setPath(spec, 'output.quality', 'draft')
    expect(spec).toEqual({ output: { quality: 'draft' } })
  })

  it('undefined remove a chave, e em lista remove o item', () => {
    const spec: Record<string, unknown> = { output: { fps: 30, guides: true }, tracks: [1, 2, 3] }
    setPath(spec, 'output.fps', undefined)
    setPath(spec, 'tracks.1', undefined)
    expect(spec).toEqual({ output: { guides: true }, tracks: [1, 3] })
  })

  it('ignora caminho que mexeria no protótipo', () => {
    const spec: Record<string, unknown> = {}
    setPath(spec, '__proto__.polluted', true)
    setPath(spec, 'a.constructor.prototype.x', 1)
    expect(({} as Record<string, unknown>).polluted).toBeUndefined()
    expect(spec).toEqual({})
  })
})

describe('pruneEmpty', () => {
  it('tira undefined, null e texto vazio', () => {
    expect(pruneEmpty({ a: 1, b: undefined, c: null, d: '', e: 'x', f: 0, g: false })).toEqual({
      a: 1,
      e: 'x',
      f: 0,
      g: false,
    })
  })

  it('tira os objetos que ficam vazios, em qualquer profundidade', () => {
    expect(pruneEmpty({ output: { fps: null }, audio: { music: { src: '' } }, keep: { x: 1 } })).toEqual({
      keep: { x: 1 },
    })
  })

  it('mantém listas, mesmo vazias, e poda o que há dentro dos itens', () => {
    expect(pruneEmpty({ overlays: [], timeline: [{ src: '', start: 0 }, { title: 'a', subtitle: null }] })).toEqual({
      overlays: [],
      timeline: [{ start: 0 }, { title: 'a' }],
    })
  })

  it('não altera o que recebe', () => {
    const original = { a: { b: '' }, c: [{ d: null }] }
    const copy = JSON.parse(JSON.stringify(original))
    pruneEmpty(original)
    expect(original).toEqual(copy)
  })
})

describe('cloneJson', () => {
  it('copia sem compartilhar referências', () => {
    const original = { a: { b: [1, 2] } }
    const copy = cloneJson(original)
    copy.a.b.push(3)
    expect(original.a.b).toEqual([1, 2])
  })
})

describe('isAbsolutePath', () => {
  it('reconhece unidade, pasta de rede e raiz', () => {
    expect(isAbsolutePath('C:\\Videos\\a.mp4')).toBe(true)
    expect(isAbsolutePath('D:/Videos/a.mp4')).toBe(true)
    expect(isAbsolutePath('\\\\servidor\\pasta\\a.mp4')).toBe(true)
    expect(isAbsolutePath('/home/a.mp4')).toBe(true)
  })

  it('caminho relativo ou vazio não é absoluto', () => {
    expect(isAbsolutePath('cam2.mp4')).toBe(false)
    expect(isAbsolutePath('cards/abertura.png')).toBe(false)
    expect(isAbsolutePath('logo')).toBe(false)
    expect(isAbsolutePath('')).toBe(false)
  })
})

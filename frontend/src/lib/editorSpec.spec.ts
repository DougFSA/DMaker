import { describe, expect, it } from 'vitest'
import type { SpecDocument } from '@/api'
import { getPath, setPath } from './editorPaths'
import {
  addAudioTrack,
  addSource,
  applySyncValues,
  cleanSourceName,
  completeFocusPair,
  convertOverlay,
  convertSegment,
  describeOverlay,
  describeSegment,
  duplicateInList,
  moveInList,
  newOverlay,
  newSegment,
  nextSourceName,
  normalizeSpec,
  planSync,
  removeFromList,
  removeSource,
  renameSource,
  setCaptionsEnabled,
  setMusicEnabled,
  setOrigin,
  setSyncMode,
  stableKey,
  syncModeOf,
} from './editorSpec'

function multicam(): SpecDocument {
  return {
    name: 'p',
    master: 'palco',
    sources: {
      palco: { src: 'a.mp4', sync: 0 },
      mesa: { src: 'b.wav', sync: 'auto' },
    },
    timeline: [
      { type: 'clip', source: 'mesa', start: 0 },
      { type: 'clip', src: 'c.mp4' },
      { type: 'card', title: 'x' },
    ],
    overlays: [
      { type: 'video', source: 'mesa', start: 1 },
      { type: 'text', text: 'oi' },
    ],
    audio: { tracks: [{ source: 'mesa', volume: 0.5 }, { source: 'palco', volume: 1 }] },
    multicam: { cameras: ['palco', 'mesa'], main: 'mesa', audio: 'mesa', at: 0 },
  }
}

describe('normalizeSpec', () => {
  it('garante as seções que o formulário lê', () => {
    expect(normalizeSpec({ name: 'p' })).toEqual({
      name: 'p',
      output: {},
      audio: {},
      overlays: [],
      timeline: [],
      sources: {},
    })
  })

  it('não troca o que já existe', () => {
    const spec = normalizeSpec({ output: { fps: 30 }, timeline: [{ type: 'card' }] })
    expect(spec.output).toEqual({ fps: 30 })
    expect(spec.timeline).toHaveLength(1)
  })
})

describe('trechos novos e troca de tipo', () => {
  it('cria cada tipo com os valores que o formulário mostra', () => {
    expect(newSegment('clip')).toMatchObject({ type: 'clip', src: '', start: 0, speed: 1, volume: 1, mute: false })
    expect(newSegment('image')).toMatchObject({ type: 'image', duration: 3, motion: 'zoom-in', motion_amount: 0.12 })
    expect(newSegment('card')).toMatchObject({ type: 'card', logo: true, motion_amount: 0.04 })
  })

  it('trocar o tipo leva rótulo, transição, enquadramento, cor, look e fades', () => {
    const old = {
      type: 'clip',
      src: 'a.mp4',
      label: 'abertura',
      transition: { type: 'fade', duration: 1 },
      reframe: { mode: 'crop' },
      color: { brightness: 0.1 },
      look: 'cinema',
      fade_in: 0.4,
    }
    const card = convertSegment(old, 'card')
    expect(card).toMatchObject({
      type: 'card',
      label: 'abertura',
      transition: { type: 'fade', duration: 1 },
      reframe: { mode: 'crop' },
      color: { brightness: 0.1 },
      look: 'cinema',
      fade_in: 0.4,
      fade_out: 0,
    })
    expect(card).not.toHaveProperty('src')
  })

  it('não inventa campos que o trecho antigo não tinha', () => {
    expect(convertSegment({ type: 'card', title: 'x' }, 'image')).not.toHaveProperty('label')
  })
})

describe('sobreposições novas e troca de tipo', () => {
  it('cria cada tipo', () => {
    expect(newOverlay('text')).toMatchObject({ type: 'text', role: 'title' })
    expect(newOverlay('image')).toMatchObject({ type: 'image', src: 'logo', position: 'top-right' })
    expect(newOverlay('video')).toMatchObject({ type: 'video', shape: 'rounded', animation: 'fade', border: 6 })
    expect(newOverlay('progress-bar')).toEqual({ type: 'progress-bar', position: 'bottom', height: 10 })
  })

  it('trocar o tipo mantém início e fim quando o novo tipo os tem', () => {
    expect(convertOverlay({ type: 'text', text: 'x', start: 2, end: 5 }, 'image')).toMatchObject({ start: 2, end: 5 })
    const bar = convertOverlay({ type: 'text', text: 'x', start: 2, end: 5 }, 'progress-bar')
    expect(bar).toEqual({ type: 'progress-bar', position: 'bottom', height: 10 })
  })
})

describe('como cada item aparece na lista', () => {
  it('a chave estável acompanha o item, não a posição', () => {
    const a = { type: 'card' }
    const b = { type: 'card' }
    const list = [a, b]
    const keyA = stableKey(a)
    const keyB = stableKey(b)
    expect(keyA).not.toBe(keyB)
    moveInList(list, 0, 1)
    expect(stableKey(list[1])).toBe(keyA)
    expect(stableKey(a)).toBe(keyA) // consultar de novo não troca a chave
  })

  it('uma cópia (duplicar) ganha chave nova, e valor que não é objeto não tem chave', () => {
    const list: Array<{ type: string }> = [{ type: 'card' }]
    duplicateInList(list, 0)
    expect(stableKey(list[0])).not.toBe(stableKey(list[1]))
    expect(stableKey('texto')).toBe(0)
    expect(stableKey(null)).toBe(0)
  })

  it('resume o trecho pelo rótulo, pelo arquivo, pela fonte ou pelo título do cartão', () => {
    expect(describeSegment({ type: 'clip', src: 'C:/midia/abertura.mp4', label: 'Entrada' })).toBe('Entrada')
    expect(describeSegment({ type: 'clip', src: 'C:/midia/abertura.mp4' })).toBe('abertura.mp4')
    expect(describeSegment({ type: 'clip', source: 'palco' })).toBe('palco')
    expect(describeSegment({ type: 'image', src: 'foto.png' })).toBe('foto.png')
    expect(describeSegment({ type: 'card', title: 'Fim' })).toBe('Fim')
    expect(describeSegment({ type: 'clip' })).toBe('')
  })

  it('resume a sobreposição pelo texto, pelo logo ou pelo arquivo', () => {
    expect(describeOverlay({ type: 'text', text: 'Olá' })).toBe('Olá')
    expect(describeOverlay({ type: 'image', src: 'logo:symbol' })).toBe('logo da marca')
    expect(describeOverlay({ type: 'image', src: 'C:/midia/selo.png' })).toBe('selo.png')
    expect(describeOverlay({ type: 'video', source: 'palco' })).toBe('palco')
    expect(describeOverlay({ type: 'progress-bar' })).toBe('')
  })
})

describe('foco do enquadramento', () => {
  it('completa o par quando só um dos dois foi preenchido', () => {
    const spec: SpecDocument = { timeline: [{ reframe: { focus: [] } }] }
    setPath(spec, 'timeline.0.reframe.focus.1', 0.9)
    completeFocusPair(spec, 'timeline.0.reframe.focus.1')
    expect(getPath(spec, 'timeline.0.reframe.focus')).toEqual([0.5, 0.9])
  })

  it('não mexe em outros caminhos', () => {
    const spec: SpecDocument = { timeline: [{ speed: 2 }] }
    completeFocusPair(spec, 'timeline.0.speed')
    expect(spec).toEqual({ timeline: [{ speed: 2 }] })
  })
})

describe('listas', () => {
  it('sobe e desce, e avisa quando já está na ponta', () => {
    const list = ['a', 'b', 'c']
    expect(moveInList(list, 1, -1)).toBe(true)
    expect(list).toEqual(['b', 'a', 'c'])
    expect(moveInList(list, 2, 1)).toBe(false)
    expect(moveInList(list, 0, -1)).toBe(false)
    expect(list).toEqual(['b', 'a', 'c'])
  })

  it('duplica uma cópia independente logo depois', () => {
    const list: Array<{ x: number[] }> = [{ x: [1] }, { x: [2] }]
    expect(duplicateInList(list, 0)).toBe(true)
    expect(list).toHaveLength(3)
    ;(list[1] as { x: number[] }).x.push(9)
    expect((list[0] as { x: number[] }).x).toEqual([1])
  })

  it('remove respeitando o mínimo', () => {
    const list = ['a', 'b']
    expect(removeFromList(list, 0, 1)).toBe(true)
    expect(removeFromList(list, 0, 1)).toBe(false)
    expect(list).toEqual(['b'])
    expect(removeFromList(list, 0)).toBe(true)
    expect(list).toEqual([])
  })
})

describe('fontes sincronizadas', () => {
  it('escolhe o primeiro nome livre e limpa o nome digitado', () => {
    expect(nextSourceName({ sources: { fonte1: {}, fonte3: {} } })).toBe('fonte2')
    expect(cleanSourceName('  câmera  do altar ')).toBe('câmera-do-altar')
  })

  it('acrescenta uma fonte automática', () => {
    const spec: SpecDocument = { sources: {} }
    expect(addSource(spec)).toBe('fonte1')
    expect(spec.sources).toEqual({ fonte1: { src: '', sync: 'auto', audio_stream: 0 } })
  })

  it('renomear leva junto todas as referências e mantém a ordem', () => {
    const spec = multicam()
    expect(renameSource(spec, 'mesa', ' mesa do dj ')).toBe('renamed')
    expect(Object.keys(spec.sources as object)).toEqual(['palco', 'mesa-do-dj'])
    expect((spec.timeline as Array<Record<string, unknown>>)[0]?.source).toBe('mesa-do-dj')
    expect((spec.overlays as Array<Record<string, unknown>>)[0]?.source).toBe('mesa-do-dj')
    expect((spec.audio as { tracks: Array<{ source: string }> }).tracks.map((t) => t.source)).toEqual([
      'mesa-do-dj',
      'palco',
    ])
    expect(spec.multicam).toMatchObject({ cameras: ['palco', 'mesa-do-dj'], main: 'mesa-do-dj', audio: 'mesa-do-dj' })
    expect(spec.master).toBe('palco')
  })

  it('renomear a principal atualiza o master', () => {
    const spec = multicam()
    renameSource(spec, 'palco', 'altar')
    expect(spec.master).toBe('altar')
  })

  it('recusa nome vazio, igual ou já usado e não mexe em nada', () => {
    const spec = multicam()
    const before = JSON.stringify(spec)
    expect(renameSource(spec, 'mesa', '   ')).toBe('empty')
    expect(renameSource(spec, 'mesa', 'mesa')).toBe('same')
    expect(renameSource(spec, 'mesa', 'palco')).toBe('exists')
    expect(JSON.stringify(spec)).toBe(before)
  })

  it('remover deixa os clipes sem origem e tira as faixas dela', () => {
    const spec = multicam()
    removeSource(spec, 'mesa')
    expect(Object.keys(spec.sources as object)).toEqual(['palco'])
    expect((spec.timeline as Array<Record<string, unknown>>)[0]).toEqual({ type: 'clip', start: 0, src: '' })
    expect((spec.overlays as Array<Record<string, unknown>>)[0]).toMatchObject({ type: 'video', src: '' })
    expect((spec.overlays as Array<Record<string, unknown>>)[0]).not.toHaveProperty('source')
    expect((spec.audio as { tracks: unknown[] }).tracks).toEqual([{ source: 'palco', volume: 1 }])
  })

  it('remover a principal limpa o master', () => {
    const spec = multicam()
    removeSource(spec, 'palco')
    expect(spec).not.toHaveProperty('master')
  })

  it('a origem do clipe é a fonte ou o arquivo, nunca os dois', () => {
    const spec = multicam()
    setOrigin(spec, 'timeline.1', 'palco')
    expect(spec.timeline).toMatchObject([{}, { source: 'palco' }, {}])
    expect((spec.timeline as Array<Record<string, unknown>>)[1]).not.toHaveProperty('src')
    setOrigin(spec, 'timeline.1', '')
    expect((spec.timeline as Array<Record<string, unknown>>)[1]).not.toHaveProperty('source')
  })

  it('alterna entre sincronização automática e manual guardando o deslocamento', () => {
    const spec = multicam()
    expect(syncModeOf((spec.sources as Record<string, Record<string, unknown>>).mesa)).toBe('auto')
    expect(syncModeOf((spec.sources as Record<string, Record<string, unknown>>).palco)).toBe('manual')
    setSyncMode(spec, 'mesa', 'manual')
    expect((spec.sources as Record<string, Record<string, unknown>>).mesa?.sync).toBe(0)
    setSyncMode(spec, 'palco', 'manual')
    expect((spec.sources as Record<string, Record<string, unknown>>).palco?.sync).toBe(0)
    ;(spec.sources as Record<string, Record<string, unknown>>).palco!.sync = 2.5
    setSyncMode(spec, 'palco', 'manual')
    expect((spec.sources as Record<string, Record<string, unknown>>).palco?.sync).toBe(2.5)
    setSyncMode(spec, 'palco', 'auto')
    expect((spec.sources as Record<string, Record<string, unknown>>).palco?.sync).toBe('auto')
  })
})

describe('sincronizar agora', () => {
  it('pede duas fontes e o arquivo de cada uma', () => {
    expect(planSync({ sources: { a: { src: 'a.mp4' } } })).toMatchObject({ ok: false })
    expect(planSync({ sources: { a: { src: 'a.mp4' }, b: { src: '' } } })).toEqual({
      ok: false,
      reason: 'Preencha o arquivo de cada fonte antes de sincronizar.',
    })
  })

  it('usa a principal como relógio, ou a primeira quando não há principal', () => {
    const spec: SpecDocument = {
      master: 'b',
      sources: { a: { src: 'a.mp4' }, b: { src: 'b.mp4', audio_stream: 1 }, c: { src: 'c.wav' } },
    }
    expect(planSync(spec)).toEqual({
      ok: true,
      plan: {
        master: 'b',
        masterStream: 1,
        masterFile: 'b.mp4',
        others: [
          { name: 'a', file: 'a.mp4' },
          { name: 'c', file: 'c.wav' },
        ],
      },
    })
    delete spec.master
    expect(planSync(spec)).toMatchObject({ ok: true, plan: { master: 'a', masterStream: 0 } })
  })

  it('grava o deslocamento medido nas fontes pelo arquivo', () => {
    const spec = multicam()
    const applied = applySyncValues(spec, [
      { path: 'b.wav', offset_s: 1.234, confidence: 0.9, reliable: true },
      { path: 'nao-existe.wav', offset_s: 9, confidence: 0.1, reliable: false },
    ])
    expect(applied).toBe(1)
    expect((spec.sources as Record<string, Record<string, unknown>>).mesa?.sync).toBe(1.234)
  })
})

describe('legendas, música e faixas', () => {
  it('liga as legendas com os valores iniciais e desliga com null', () => {
    const spec: SpecDocument = {}
    setCaptionsEnabled(spec, true)
    expect(spec.captions).toEqual({ source: 'auto', language: 'pt', model: 'small' })
    ;(spec.captions as Record<string, unknown>).language = 'en'
    setCaptionsEnabled(spec, true)
    expect((spec.captions as Record<string, unknown>).language).toBe('en')
    setCaptionsEnabled(spec, false)
    expect(spec.captions).toBeNull()
  })

  it('liga e desliga a música', () => {
    const spec: SpecDocument = {}
    setMusicEnabled(spec, true)
    expect(spec.audio).toEqual({ music: { src: '' } })
    setMusicEnabled(spec, false)
    expect((spec.audio as Record<string, unknown>).music).toBeNull()
  })

  it('a faixa externa precisa de uma fonte', () => {
    const none: SpecDocument = { sources: {} }
    expect(addAudioTrack(none)).toBe(false)
    const spec = multicam()
    expect(addAudioTrack(spec)).toBe(true)
    expect((spec.audio as { tracks: unknown[] }).tracks.at(-1)).toEqual({ source: 'palco', volume: 1 })
  })
})

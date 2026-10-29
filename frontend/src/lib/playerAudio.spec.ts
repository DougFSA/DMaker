import { describe, expect, it } from 'vitest'
import type { TimelineView } from '@/api'
import { timelineItem, timelineTrack, timelineView } from '@/test/editorFixtures'
import { liveAudioPlan, MAX_LIVE_STREAMS } from './playerAudio'

/* O projeto do critério de aceite do DMK-20, em miniatura: câmeras mudas, uma mesa com sincronia diferente de zero e
   a 0,5, música com um span e a câmera em duas partes. Os itens são os que o servidor manda (já fatiados por corte). */

function session(): { view: TimelineView; spec: Record<string, unknown> } {
  const crossing = timelineItem(0, {
    id: 'A1-0',
    kind: 'clip-audio',
    start: 0,
    end: 20,
    in_point: 50,
    src: null,
    source: 'cam',
    path: 'C:/cam_a.mp4',
    muted: true, // a câmera está em mute: true
    extra: {
      speed: 1,
      pieces: [
        { start: 0, end: 10, in_point: 50, path: 'C:/cam_a.mp4' },
        { start: 10, end: 20, in_point: 0, path: 'C:/cam_b.mp4' },
      ],
    },
  })
  const loud = timelineItem(1, { id: 'A1-1', kind: 'clip-audio', start: 20, end: 26, in_point: 4, path: 'C:/cam_b.mp4', extra: { speed: 1 } })
  const mesa = [0, 1].map((k) =>
    timelineItem(0, {
      id: `A2-0-${k}`,
      kind: 'track',
      start: k * 10,
      end: k * 10 + 10,
      in_point: 45 + k * 10,
      src: null,
      source: 'mesa',
      path: 'C:/mesa.wav',
      extra: { offset: 0, speed: 1, volume: 0.5 },
    }),
  )
  const music = timelineItem(0, {
    id: 'MUS-0',
    kind: 'music',
    start: 2,
    end: 24,
    in_point: 8,
    src: 'musica.mp3',
    path: 'C:/musica.mp3',
    extra: { loop: true, volume: 0.3 },
  })
  const view: TimelineView = {
    ...timelineView([]),
    total: 26,
    tracks: [
      timelineTrack('V1', [], { kind: 'video' }),
      timelineTrack('A1', [crossing, loud], { kind: 'audio' }),
      timelineTrack('A2', mesa, { kind: 'audio' }),
      timelineTrack('MUS', [music], { kind: 'audio' }),
    ],
    sources: { cam: { src: 'cam_a.mp4', parts: ['cam_a.mp4', 'cam_b.mp4'], offset: 0, in_point: 0, path: 'C:/cam_a.mp4' } },
  }
  return { view, spec: { timeline: [{ volume: 1 }, { volume: 0.8 }] } }
}

const plan = (t: number, extra: Partial<Parameters<typeof liveAudioPlan>[1]> = {}) => {
  const { view, spec } = session()
  return liveAudioPlan(t, { view, spec, proxyUrls: {}, master: 1, ...extra })
}

describe('som ao vivo: só o que cobre o instante', () => {
  it('toca a mesa no ponto dela depois do corte, não o tempo da linha do tempo', () => {
    const channel = plan(14).channels.find((c) => c.trackId === 'A2')
    // o segundo corte da mesa começa em 10 s da linha do tempo e em 55 s do arquivo
    expect(channel).toMatchObject({ path: 'C:/mesa.wav', fileTime: 59, volume: 0.5, muted: false, loop: false })
  })

  it('a mesa que ainda não começou fica fora, em vez de prender em 0', () => {
    const { view, spec } = session()
    view.tracks.find((t) => t.id === 'A2')!.items = [timelineItem(0, { id: 'A2-0-0', kind: 'track', start: 4, end: 10, in_point: 0, path: 'C:/mesa.wav', extra: { offset: 0, volume: 1 } })]
    const result = liveAudioPlan(2, { view, spec, proxyUrls: {}, master: 1 })
    expect(result.channels.find((c) => c.trackId === 'A2')).toBeUndefined()
    // e quando ela começa, toca do começo do arquivo
    expect(liveAudioPlan(4.5, { view, spec, proxyUrls: {}, master: 1 }).channels.find((c) => c.trackId === 'A2')?.fileTime).toBe(0.5)
  })

  it('a câmera em mute: true não gasta um fluxo; o clipe com som toca do arquivo da parte certa', () => {
    expect(plan(5).channels.find((c) => c.trackId === 'A1')).toBeUndefined()
    const loud = plan(21).channels.find((c) => c.trackId === 'A1')
    expect(loud).toMatchObject({ path: 'C:/cam_b.mp4', fileTime: 5, volume: 0.8 })
  })

  it('o clipe que atravessa a fronteira das partes troca de arquivo sozinho', () => {
    const { view, spec } = session()
    view.tracks.find((t) => t.id === 'A1')!.items[0]!.muted = false
    const first = liveAudioPlan(4, { view, spec, proxyUrls: {}, master: 1 }).channels.find((c) => c.trackId === 'A1')
    const second = liveAudioPlan(13, { view, spec, proxyUrls: {}, master: 1 }).channels.find((c) => c.trackId === 'A1')
    expect(first).toMatchObject({ path: 'C:/cam_a.mp4', fileTime: 54 })
    expect(second).toMatchObject({ path: 'C:/cam_b.mp4', fileTime: 3 })
  })

  it('a música em loop leva o ponto do span e o volume dela; fora do span fica de fora', () => {
    const music = plan(10).channels.find((c) => c.trackId === 'MUS')
    expect(music).toMatchObject({ path: 'C:/musica.mp3', fileTime: 16, loop: true, volume: 0.3 })
    expect(plan(1).channels.find((c) => c.trackId === 'MUS')).toBeUndefined()
    expect(plan(25).channels.find((c) => c.trackId === 'MUS')).toBeUndefined()
  })

  it('mudo da trilha, mudo do item e volume geral zero não ocupam fluxo', () => {
    const { view, spec } = session()
    view.tracks.find((t) => t.id === 'A2')!.muted = true
    expect(liveAudioPlan(14, { view, spec, proxyUrls: {}, master: 1 }).channels.map((c) => c.trackId)).toEqual(['MUS'])
    expect(plan(14, { master: 0 }).channels).toEqual([])
  })

  it('mute_clips cala a câmera e as faixas externas, como no render, mas não a música', () => {
    const { view, spec } = session()
    view.tracks.find((t) => t.id === 'A1')!.items[0]!.muted = false
    const muted = liveAudioPlan(14, { view, spec: { ...spec, audio: { mute_clips: true } }, proxyUrls: {}, master: 1 })
    expect(muted.channels.map((c) => c.trackId)).toEqual(['MUS'])
    const plain = liveAudioPlan(14, { view, spec, proxyUrls: {}, master: 1 })
    expect(plain.channels.map((c) => c.trackId)).toEqual(['A1', 'A2', 'MUS'])
  })

  it('o volume e o mudo mudam o plano seguinte, sem nada guardado', () => {
    const before = plan(14).channels.find((c) => c.trackId === 'A2')
    const { view, spec } = session()
    view.tracks.find((t) => t.id === 'A2')!.items.forEach((item) => (item.extra.volume = 0.25))
    const after = liveAudioPlan(14, { view, spec, proxyUrls: {}, master: 1 }).channels.find((c) => c.trackId === 'A2')
    expect(before?.volume).toBe(0.5)
    expect(after?.volume).toBe(0.25)
    expect(plan(14, { master: 0.5 }).channels.find((c) => c.trackId === 'A2')?.volume).toBe(0.25)
  })

  it('a velocidade do trecho vai para o elemento', () => {
    const { view, spec } = session()
    view.tracks.find((t) => t.id === 'A2')!.items.forEach((item) => (item.extra.speed = 2))
    expect(liveAudioPlan(14, { view, spec, proxyUrls: {}, master: 1 }).channels.find((c) => c.trackId === 'A2')?.speed).toBe(2)
  })

  it('o proxy pronto troca o endereço do som da câmera', () => {
    const result = plan(21, { proxyUrls: { 'C:/cam_b.mp4': '/api/file?path=proxy-b' } })
    expect(result.channels.find((c) => c.trackId === 'A1')?.url).toBe('/api/file?path=proxy-b')
  })

  it('item de arquivo ausente não toca', () => {
    const { view, spec } = session()
    view.tracks.find((t) => t.id === 'A2')!.items.forEach((item) => (item.missing = true))
    expect(liveAudioPlan(14, { view, spec, proxyUrls: {}, master: 1 }).channels.map((c) => c.trackId)).toEqual(['MUS'])
  })
})

describe('som ao vivo: o limite de fluxos', () => {
  function crowded(): TimelineView {
    const { view } = session()
    view.tracks.find((t) => t.id === 'A1')!.items[0]!.muted = false
    for (const id of ['A3', 'A4', 'A5']) {
      view.tracks.push(
        timelineTrack(id, [timelineItem(0, { id: `${id}-0`, kind: 'track', start: 0, end: 20, in_point: 0, path: `C:/${id}.wav`, extra: { offset: 0, volume: 1 } })], { kind: 'audio' }),
      )
    }
    return view
  }

  it('acima do limite, ficam a câmera e as primeiras faixas; a música, que vem por último, cai fora', () => {
    const result = liveAudioPlan(14, { view: crowded(), spec: { timeline: [{}] }, proxyUrls: {}, master: 1 })
    expect(result.channels).toHaveLength(MAX_LIVE_STREAMS)
    expect(result.channels.map((c) => c.trackId)).toEqual(['A1', 'A2', 'A3'])
    expect(result.dropped).toEqual(['A4', 'A5', 'MUS'])
  })

  it('o limite pode ser menor (o vídeo já usa conexões)', () => {
    const result = liveAudioPlan(14, { view: crowded(), spec: { timeline: [{}] }, proxyUrls: {}, master: 1, maxStreams: 1 })
    expect(result.channels.map((c) => c.trackId)).toEqual(['A1'])
    expect(liveAudioPlan(14, { view: crowded(), spec: { timeline: [{}] }, proxyUrls: {}, master: 1, maxStreams: 0 }).channels).toEqual([])
  })
})

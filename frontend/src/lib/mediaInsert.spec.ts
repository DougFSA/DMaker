import { describe, expect, it } from 'vitest'
import type { TimelineView } from '@/api'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import type { MediaEntry } from './media'
import {
  entryFromPath,
  kindFromPath,
  kindLabel,
  mediaDurationLabel,
  overlayFromEntry,
  parseMediaPayload,
  planAddCard,
  planAddFile,
  planAddLogo,
  planAddText,
  planAppend,
  planDrop,
  planInsertAtTime,
  planSetMusic,
  segmentFromEntry,
} from './mediaInsert'

const clipEntry: MediaEntry = { id: 'file:C:/m/a.mp4', kind: 'clip', label: 'a.mp4', path: 'C:/m/a.mp4', src: 'a.mp4' }
const imageEntry: MediaEntry = { id: 'file:C:/m/logo.png', kind: 'image', label: 'logo.png', path: 'C:/m/logo.png', src: 'logo.png' }
const audioEntry: MediaEntry = { id: 'file:C:/m/s.mp3', kind: 'audio', label: 's.mp3', path: 'C:/m/s.mp3', src: 's.mp3' }
const sourceEntry: MediaEntry = { id: 'source:cam1', kind: 'clip', label: 'cam1', path: 'C:/m/cam1.mp4', source: 'cam1' }

/** Uma V1 de três trechos de 3 s (0 a 9 s) e as demais trilhas pedidas. */
function view(extra: Array<ReturnType<typeof timelineTrack>> = [], total = 9): TimelineView {
  return {
    total,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [timelineTrack('V1', [timelineItem(0), timelineItem(1), timelineItem(2)]), ...extra],
    sources: {},
    warnings: [],
  }
}

describe('o tipo de um arquivo', () => {
  it('sai da extensão, sem diferenciar maiúscula, e o que não se conhece entra como vídeo', () => {
    expect(kindFromPath('C:/m/a.MP4')).toBe('clip')
    expect(kindFromPath('C:/m/a.mov')).toBe('clip')
    expect(kindFromPath('C:/m/foto.JPG')).toBe('image')
    expect(kindFromPath('C:/m/foto.webp')).toBe('image')
    expect(kindFromPath('C:/m/musica.wav')).toBe('audio')
    expect(kindFromPath('C:/m/musica.m4a')).toBe('audio')
    expect(kindFromPath('C:/m/sem-extensao')).toBe('clip')
    expect(kindFromPath('C:/pasta.v2/arquivo')).toBe('clip')
  })

  it('a entrada de um arquivo escolhido leva o nome, o caminho e o src da spec', () => {
    expect(entryFromPath('C:\\midia\\Praia.PNG')).toEqual({
      id: 'file:C:\\midia\\Praia.PNG',
      kind: 'image',
      label: 'Praia.PNG',
      path: 'C:\\midia\\Praia.PNG',
      src: 'C:\\midia\\Praia.PNG',
    })
  })

  it('os rótulos e a duração saem em português', () => {
    expect(kindLabel('clip')).toBe('vídeo')
    expect(kindLabel('image')).toBe('imagem')
    expect(kindLabel('audio')).toBe('áudio')
    expect(mediaDurationLabel(3.44)).toBe('3,4 s')
    expect(mediaDurationLabel(59.96)).toBe('60,0 s')
    expect(mediaDurationLabel(65)).toBe('1:05')
    expect(mediaDurationLabel(600)).toBe('10:00')
  })
})

describe('parseMediaPayload', () => {
  it('lê de volta o que o arrastar levou', () => {
    expect(parseMediaPayload(JSON.stringify(clipEntry))).toEqual(clipEntry)
    expect(parseMediaPayload(JSON.stringify(sourceEntry))).toEqual(sourceEntry)
  })

  it('texto que não é uma entrada de mídia vale nada', () => {
    expect(parseMediaPayload('não é json')).toBeNull()
    expect(parseMediaPayload('42')).toBeNull()
    expect(parseMediaPayload('null')).toBeNull()
    expect(parseMediaPayload(JSON.stringify({ id: 'x', kind: 'hologram', path: 'p', src: 's' }))).toBeNull()
    expect(parseMediaPayload(JSON.stringify({ id: 'x', kind: 'clip', path: 'p' }))).toBeNull()
    expect(parseMediaPayload(JSON.stringify({ kind: 'clip', path: 'p', src: 's' }))).toBeNull()
  })
})

describe('o trecho e a sobreposição de uma entrada', () => {
  it('vídeo vira clipe inteiro; fonte sincronizada vira clipe da fonte; imagem vira trecho de 3 s com movimento', () => {
    expect(segmentFromEntry(clipEntry)).toEqual({ type: 'clip', start: 0, speed: 1, volume: 1, mute: false, src: 'a.mp4' })
    expect(segmentFromEntry(sourceEntry)).toEqual({ type: 'clip', start: 0, speed: 1, volume: 1, mute: false, source: 'cam1' })
    expect(segmentFromEntry(imageEntry)).toEqual({ type: 'image', src: 'logo.png', duration: 3, motion: 'zoom-in', motion_amount: 0.12 })
  })

  it('a imagem solta fora da V1 vira imagem no canto, por 3 s a partir do ponto', () => {
    expect(overlayFromEntry(imageEntry, 2, 9)).toEqual({
      type: 'image',
      src: 'logo.png',
      position: 'top-right',
      width: 0.22,
      opacity: 1,
      start: 2,
      end: 5,
    })
  })

  it('o vídeo solto fora da V1 vira PiP no canto, da fonte quando é ela', () => {
    expect(overlayFromEntry(clipEntry, 1, 9)).toMatchObject({ type: 'video', src: 'a.mp4', start: 1, end: 4, position: 'bottom-right', shape: 'rounded' })
    const fromSource = overlayFromEntry(sourceEntry, 1, 9)
    expect(fromSource).toMatchObject({ type: 'video', source: 'cam1' })
    expect(fromSource).not.toHaveProperty('src')
  })

  it('o fim não passa do fim do vídeo; sem espaço, a sobreposição fica sem fim', () => {
    expect(overlayFromEntry(clipEntry, 8, 9)).toMatchObject({ start: 8, end: 9 })
    const atEnd = overlayFromEntry(clipEntry, 9, 9)
    expect(atEnd).toMatchObject({ start: 9 })
    expect(atEnd).not.toHaveProperty('end')
  })
})

describe('acrescentar e inserir na V1', () => {
  it('a tecla A põe a entrada no fim da V1', () => {
    expect(planAppend(view(), clipEntry)).toEqual({
      ok: true,
      ops: [{ type: 'insert', index: 3, segment: segmentFromEntry(clipEntry) }],
    })
  })

  it('a tecla V põe a entrada na posição do cursor', () => {
    const at = (time: number) => (planInsertAtTime(view(), clipEntry, time) as { ok: true; ops: Array<{ index: number }> }).ops[0]?.index
    expect(at(0)).toBe(1)
    expect(at(3)).toBe(2) // no começo de um trecho a entrada entra depois dele
    expect(at(4.5)).toBe(2)
    expect(at(9)).toBe(3)
  })

  it('áudio não entra na V1: o aviso manda para o botão Música', () => {
    expect(planAppend(view(), audioEntry)).toEqual({ ok: false, message: 'Arquivos de áudio entram pelo botão "Música", não na V1.' })
    expect(planInsertAtTime(view(), audioEntry, 1).ok).toBe(false)
  })

  it('V1 bloqueada avisa em vez de inserir', () => {
    const locked = view()
    locked.tracks[0]!.locked = true
    expect(planAppend(locked, clipEntry)).toEqual({ ok: false, message: 'A trilha V1 está bloqueada (cadeado no cabeçalho).' })
    expect(planAddCard(locked).ok).toBe(false)
  })

  it('numa V1 vazia a entrada entra na posição zero', () => {
    const empty = view()
    empty.tracks[0]!.items = []
    expect(planAppend(empty, clipEntry)).toMatchObject({ ok: true, ops: [{ index: 0 }] })
    expect(planInsertAtTime(empty, clipEntry, 5)).toMatchObject({ ok: true, ops: [{ index: 0 }] })
  })
})

describe('soltar na linha do tempo', () => {
  const existing = [{ type: 'text', text: 'Olá', start: 0 }]

  it('na V1 insere no ponto', () => {
    expect(planDrop(view(), existing, clipEntry, { trackId: 'V1', time: 4 })).toMatchObject({ ok: true, ops: [{ type: 'insert', index: 2 }] })
  })

  it('em outra trilha acrescenta uma sobreposição à lista que a spec já tem', () => {
    const plan = planDrop(view(), existing, clipEntry, { trackId: 'V2', time: 2 })
    expect(plan).toMatchObject({ ok: true, ops: [{ type: 'set_field', path: 'overlays' }] })
    const value = (plan as { ops: Array<{ value: unknown[] }> }).ops[0]?.value
    expect(value).toHaveLength(2)
    expect(value?.[0]).toEqual(existing[0])
    expect(value?.[1]).toMatchObject({ type: 'video', src: 'a.mp4', start: 2 })
    expect(existing).toHaveLength(1) // a lista da spec não é alterada
  })

  it('a imagem solta no TX ou no GR vira sobreposição de imagem', () => {
    const plan = planDrop(view(), [], imageEntry, { trackId: 'GR', time: 0 })
    expect((plan as { ops: Array<{ value: unknown[] }> }).ops[0]?.value[0]).toMatchObject({ type: 'image', src: 'logo.png' })
  })

  it('áudio solto em qualquer trilha é recusado com o aviso do botão Música', () => {
    expect(planDrop(view(), [], audioEntry, { trackId: 'V1', time: 0 }).ok).toBe(false)
    expect(planDrop(view(), [], audioEntry, { trackId: 'V2', time: 0 })).toEqual({
      ok: false,
      message: 'Arquivos de áudio entram pelo botão "Música", não como sobreposição.',
    })
  })

  it('fora das trilhas (na régua) e em trilha bloqueada não há onde soltar', () => {
    expect(planDrop(view(), [], clipEntry, { trackId: null, time: 1 })).toEqual({
      ok: false,
      message: 'Solte o arquivo sobre uma trilha da linha do tempo.',
    })
    const withLockedTx = view([timelineTrack('TX', [], { kind: 'text', locked: true })])
    expect(planDrop(withLockedTx, [], clipEntry, { trackId: 'TX', time: 1 })).toEqual({
      ok: false,
      message: 'A trilha TX está bloqueada (cadeado no cabeçalho).',
    })
  })
})

describe('os botões Texto, Cartão, Logo e Música', () => {
  it('Texto põe uma linha de texto no cursor, por 3 s', () => {
    expect(planAddText(view(), [], 2)).toEqual({
      ok: true,
      ops: [{ type: 'set_field', path: 'overlays', value: [{ type: 'text', text: 'Novo texto', role: 'title', start: 2, end: 5 }] }],
    })
  })

  it('Logo põe o logo da marca no canto, no cursor', () => {
    const plan = planAddLogo(view(), [{ type: 'progress-bar' }], 1)
    const value = (plan as { ops: Array<{ value: unknown[] }> }).ops[0]?.value
    expect(value).toHaveLength(2)
    expect(value?.[1]).toEqual({ type: 'image', src: 'logo', position: 'top-right', width: 0.22, start: 1, end: 4 })
  })

  it('Texto e Logo respeitam o cadeado da trilha onde vão', () => {
    expect(planAddText(view([timelineTrack('TX', [], { kind: 'text', locked: true })]), [], 0).ok).toBe(false)
    expect(planAddLogo(view([timelineTrack('GR', [], { kind: 'graphics', locked: true })]), [], 0).ok).toBe(false)
  })

  it('Cartão insere um cartão novo no fim da V1', () => {
    expect(planAddCard(view())).toEqual({
      ok: true,
      ops: [{ type: 'insert', index: 3, segment: { type: 'card', title: 'Novo cartão', duration: 3, motion: 'zoom-in' } }],
    })
  })

  it('Música cria a música com volume baixo; com música já no projeto, troca só o arquivo', () => {
    expect(planSetMusic(undefined, 'C:/m/s.mp3')).toEqual({
      ok: true,
      ops: [{ type: 'set_field', path: 'audio.music', value: { src: 'C:/m/s.mp3', volume: 0.18 } }],
    })
    expect(planSetMusic(null, 'C:/m/s.mp3')).toMatchObject({ ops: [{ path: 'audio.music' }] })
    expect(planSetMusic({ src: 'velha.mp3', volume: 0.5 }, 'C:/m/nova.mp3')).toEqual({
      ok: true,
      ops: [{ type: 'set_field', path: 'audio.music.src', value: 'C:/m/nova.mp3' }],
    })
  })

  it('+ Arquivo: áudio vira a música; vídeo e imagem entram no fim da V1', () => {
    expect(planAddFile(view(), undefined, 'C:/m/s.mp3')).toMatchObject({ ok: true, ops: [{ path: 'audio.music' }] })
    expect(planAddFile(view(), undefined, 'C:/m/a.mp4')).toMatchObject({
      ok: true,
      ops: [{ type: 'insert', index: 3, segment: { type: 'clip', src: 'C:/m/a.mp4' } }],
    })
    expect(planAddFile(view(), undefined, 'C:/m/foto.png')).toMatchObject({
      ok: true,
      ops: [{ type: 'insert', segment: { type: 'image', src: 'C:/m/foto.png' } }],
    })
  })
})

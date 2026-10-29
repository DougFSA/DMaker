import { describe, expect, it } from 'vitest'
import { timelineItem } from '@/test/editorFixtures'
import {
  audioGain,
  bumpedRate,
  clampPlaybackRate,
  clipPlayback,
  fileOffset,
  fileTime,
  fileUrl,
  formatTimecode,
  isExternalAudioTrack,
  itemAt,
  mediaUrl,
  playableTime,
  rateLabel,
  RESEEK_WINDOW_S,
  SEEK_GRACE_MS,
  shouldSeek,
  SYNC_TOLERANCE_S,
} from './player'

const offsets = (name: string) => ({ cam1: 12.5, cam2: -3 })[name] ?? 0

describe('itemAt', () => {
  const items = [timelineItem(0), timelineItem(1)] // 0 a 3 e 3 a 6

  it('acha o item que cobre o instante, com o início incluído e o fim excluído', () => {
    expect(itemAt(items, 0)?.index).toBe(0)
    expect(itemAt(items, 2.99)?.index).toBe(0)
    expect(itemAt(items, 3)?.index).toBe(1)
    expect(itemAt(items, 6)).toBeNull()
    expect(itemAt(items, -1)).toBeNull()
  })

  it('trilha sem item ou ausente não toca nada', () => {
    expect(itemAt([], 1)).toBeNull()
    expect(itemAt(undefined, 1)).toBeNull()
  })
})

describe('fileTime e fileOffset', () => {
  it('item fatiado por corte: o in_point já é tempo no arquivo e o offset é zero', () => {
    // a mesa a 0,5: o corte começa em 10 s da linha do tempo e em 23 s do arquivo
    const slice = timelineItem(0, { start: 10, end: 25, in_point: 23, extra: { offset: 0, speed: 1 } })
    expect(fileOffset(slice, offsets)).toBe(0)
    expect(fileTime(slice, 10, 1, offsets)).toBe(23)
    expect(fileTime(slice, 14, 1, offsets)).toBe(27)
  })

  it('a velocidade do trecho anda mais rápido pelo arquivo', () => {
    const slice = timelineItem(0, { start: 0, end: 5, in_point: 10, extra: { offset: 0 } })
    expect(fileTime(slice, 2, 2, offsets)).toBe(14)
  })

  it('sem offset explícito, desconta o da fonte nomeada', () => {
    const clip = timelineItem(0, { start: 0, in_point: 40, source: 'cam1', extra: {} })
    expect(fileOffset(clip, offsets)).toBe(12.5)
    expect(fileTime(clip, 4, 1, offsets)).toBe(31.5)
    expect(fileOffset(timelineItem(0, { source: 'cam2', extra: {} }), offsets)).toBe(-3)
    expect(fileOffset(timelineItem(0, { extra: {} }), offsets)).toBe(0)
  })
})

describe('playableTime', () => {
  it('nunca devolve tempo negativo: a faixa ainda não começou e o elemento pausa', () => {
    expect(playableTime(-0.001, 100, false)).toBeNull()
    expect(playableTime(-5, 100, true)).toBeNull()
    expect(playableTime(Number.NaN, 100, false)).toBeNull()
    expect(playableTime(0, 100, false)).toBe(0)
  })

  it('além do fim do arquivo pausa, ou dá a volta quando é música em loop', () => {
    expect(playableTime(100, 100, false)).toBeNull()
    expect(playableTime(130, 100, false)).toBeNull()
    expect(playableTime(130, 100, true)).toBe(30)
  })

  it('sem a duração ainda (metadados não chegaram), vale o tempo pedido', () => {
    expect(playableTime(42, Number.NaN, false)).toBe(42)
    expect(playableTime(42, 0, true)).toBe(42)
    expect(playableTime(42, Number.POSITIVE_INFINITY, false)).toBe(42)
  })
})

describe('clipPlayback', () => {
  it('clipe de um arquivo só: o caminho de reserva e o tempo na fonte', () => {
    const clip = timelineItem(0, { start: 0, end: 3, in_point: 2, extra: {} })
    expect(clipPlayback(clip, 1, 1, offsets, 'C:/a.mp4')).toEqual({ path: 'C:/a.mp4', fileTime: 3 })
  })

  it('fonte em partes: toca o arquivo da parte que grava o instante, com o ponto dela', () => {
    const clip = timelineItem(0, {
      start: 0,
      end: 20,
      in_point: 50,
      extra: {
        pieces: [
          { start: 0, end: 10, in_point: 50, path: 'C:/cam_a.mp4' },
          { start: 10, end: 20, in_point: 0, path: 'C:/cam_b.mp4' },
        ],
      },
    })
    expect(clipPlayback(clip, 4, 1, offsets, 'C:/cam_a.mp4')).toEqual({ path: 'C:/cam_a.mp4', fileTime: 54 })
    // na segunda parte, o ponto é o dela (recomeça do início do arquivo), não o do clipe
    expect(clipPlayback(clip, 13, 1, offsets, 'C:/cam_a.mp4')).toEqual({ path: 'C:/cam_b.mp4', fileTime: 3 })
  })

  it('fora dos pedaços cai no primeiro (antes) ou no último (depois)', () => {
    const clip = timelineItem(0, {
      extra: {
        pieces: [
          { start: 5, end: 10, in_point: 1, path: 'a' },
          { start: 10, end: 15, in_point: 0, path: 'b' },
        ],
      },
    })
    expect(clipPlayback(clip, 2, 1, offsets, null).path).toBe('a')
    expect(clipPlayback(clip, 20, 1, offsets, null).path).toBe('b')
  })
})

describe('audioGain', () => {
  it('multiplica o volume do item pelo geral', () => {
    const track = timelineItem(0, { extra: { volume: 0.5 } })
    expect(audioGain(track, false, 0.8)).toEqual({ muted: false, volume: 0.4 })
  })

  it('o volume de um item acima de 1 não passa do máximo do elemento', () => {
    expect(audioGain(timelineItem(0, { extra: { volume: 3 } }), false, 1).volume).toBe(1)
  })

  it('mudo vem do item, da trilha ou de qualquer volume zerado', () => {
    const plain = timelineItem(0, { extra: { volume: 1 } })
    expect(audioGain({ ...plain, muted: true }, false, 1)).toEqual({ muted: true, volume: 0 })
    expect(audioGain(plain, true, 1)).toEqual({ muted: true, volume: 0 })
    expect(audioGain(plain, false, 0)).toEqual({ muted: true, volume: 0 })
    expect(audioGain(timelineItem(0, { extra: { volume: 0 } }), false, 1)).toEqual({ muted: true, volume: 0 })
  })

  it('o volume do trecho pode vir da spec quando o item da vista não o carrega', () => {
    const clipAudio = timelineItem(0, { kind: 'clip-audio', extra: { speed: 1 } })
    expect(audioGain(clipAudio, false, 1, 0.25)).toEqual({ muted: false, volume: 0.25 })
    expect(audioGain(clipAudio, false, 1, 0)).toEqual({ muted: true, volume: 0 })
  })
})

describe('isExternalAudioTrack', () => {
  it('são a música e as faixas A2 em diante, não a A1 nem a narração', () => {
    for (const id of ['MUS', 'A2', 'A3', 'A10']) expect(isExternalAudioTrack({ id }), id).toBe(true)
    for (const id of ['A1', 'NAR', 'V1', 'TX', 'CC', 'A']) expect(isExternalAudioTrack({ id }), id).toBe(false)
  })
})

describe('shouldSeek', () => {
  it('dentro da tolerância não busca', () => {
    expect(shouldSeek(10, 10 + SYNC_TOLERANCE_S - 0.01, 0, null, 1)).toBe(false)
    expect(shouldSeek(10, 10.4, 0, null, 1)).toBe(true)
  })

  it('logo depois de uma busca espera o elemento carregar, em vez de buscar a cada quadro', () => {
    const last = { target: 20, at: 1000 }
    // 300 ms depois o alvo previsto é 20,3: o relógio andou junto, a busca anterior ainda está carregando
    expect(shouldSeek(5, 20.3, 1300, last, 1)).toBe(false)
    // o alvo saltou além da janela: é outra busca
    expect(shouldSeek(5, 20.3 + RESEEK_WINDOW_S + 0.1, 1300, last, 1)).toBe(true)
    // passada a carência, busca de novo
    expect(shouldSeek(5, 20.3 + SEEK_GRACE_MS / 1000, 1000 + SEEK_GRACE_MS + 1, last, 1)).toBe(true)
  })

  it('a velocidade de arquivo entra na previsão', () => {
    const last = { target: 20, at: 1000 }
    expect(shouldSeek(5, 20.4, 1200, last, 2)).toBe(false) // 20 + 0,2 s * 2
  })
})

describe('formatTimecode', () => {
  it('escreve HH:MM:SS:QQ com os quadros do fps', () => {
    expect(formatTimecode(0, 30)).toBe('00:00:00:00')
    expect(formatTimecode(1.5, 30)).toBe('00:00:01:15')
    expect(formatTimecode(61 + 1 / 30, 30)).toBe('00:01:01:01')
    expect(formatTimecode(3600 + 59.48, 25)).toBe('01:00:59:12')
  })

  it('tempo inválido ou fps ausente não quebra', () => {
    expect(formatTimecode(-4, 30)).toBe('00:00:00:00')
    expect(formatTimecode(Number.NaN, 30)).toBe('00:00:00:00')
    expect(formatTimecode(2, 0)).toBe('00:00:02:00')
  })
})

describe('bumpedRate e rateLabel', () => {
  it('o primeiro toque anda a 1x e repetir dobra até 8x', () => {
    expect(bumpedRate(1, 0)).toBe(1)
    expect(bumpedRate(1, 1)).toBe(2)
    expect(bumpedRate(1, 2)).toBe(4)
    expect(bumpedRate(1, 4)).toBe(8)
    expect(bumpedRate(1, 8)).toBe(8)
  })

  it('trocar de direção volta a 1x, e o J anda para trás', () => {
    expect(bumpedRate(-1, 4)).toBe(-1)
    expect(bumpedRate(-1, 0)).toBe(-1)
    expect(bumpedRate(-1, -1)).toBe(-2)
    expect(bumpedRate(1, -8)).toBe(1)
  })

  it('escreve a velocidade para a tela', () => {
    expect(rateLabel(0)).toBe('Pausado')
    expect(rateLabel(1)).toBe('1x')
    expect(rateLabel(-2)).toBe('-2x')
    expect(rateLabel(0.5)).toBe('0.5x')
  })
})

describe('endereços e limites', () => {
  it('o proxy pronto vence o arquivo original', () => {
    expect(mediaUrl('C:/a b.mp4', {})).toBe(`/api/file?path=${encodeURIComponent('C:/a b.mp4')}`)
    expect(mediaUrl('C:/a.mp4', { 'C:/a.mp4': '/api/file?path=proxy' })).toBe('/api/file?path=proxy')
    expect(mediaUrl(null, {})).toBeNull()
    expect(fileUrl('X:/v.mp4')).toBe('/api/file?path=X%3A%2Fv.mp4')
  })

  it('a velocidade do elemento fica entre o que o navegador aceita', () => {
    expect(clampPlaybackRate(100)).toBe(16)
    expect(clampPlaybackRate(0.001)).toBe(0.0625)
    expect(clampPlaybackRate(2)).toBe(2)
  })
})

import { describe, expect, it } from 'vitest'
import type { AudioPresetInfo } from '@/api'
import {
  bitrateModeLabel,
  buildAudioExportRequest,
  conflictQuestion,
  emptyForm,
  formatControls,
  isAudioPresetId,
  loudnessName,
  loudnessOptions,
  parseInstant,
} from './audioExport'

const MP3: AudioPresetInfo = {
  id: 'audio/mp3',
  name: 'MP3',
  extension: '.mp3',
  lossless: false,
  sample_rate: 48000,
  channels: 2,
  bit_depths: [],
  bit_depth: null,
  bitrate_modes: ['cbr', 'vbr', 'abr'],
  bitrate_mode: 'cbr',
  bitrate_k: 192,
  quality: 2,
  quality_range: [0, 9],
  allowed_sample_rates: [],
  default_label: 'CBR 192 kbps',
  notes: '',
}
const WAV: AudioPresetInfo = { ...MP3, id: 'audio/wav', name: 'WAV', lossless: true, bit_depths: [16, 24, 32], bit_depth: 16, bitrate_modes: [], bitrate_mode: null, bitrate_k: null, quality: null }

describe('audioExport', () => {
  it('reconhece o preset de áudio pelo id', () => {
    expect(isAudioPresetId('audio/mp3')).toBe(true)
    expect(isAudioPresetId('instagram/reels')).toBe(false)
    expect(isAudioPresetId(undefined)).toBe(false)
  })

  it('oferece os três alvos de loudness pelo nome e acha o nome de um valor da spec', () => {
    const targets = { redes: -14, podcast: -16, broadcast: -23 }
    expect(loudnessOptions(targets).map((o) => o.label)).toEqual([
      'Redes (-14 LUFS)',
      'Podcast (-16 LUFS)',
      'Broadcast (EBU R128) (-23 LUFS)',
    ])
    expect(loudnessName(targets, -16)).toBe('podcast')
    expect(loudnessName(targets, -18)).toBe('')
  })

  it('cada formato mostra só os controles que valem nele', () => {
    expect(formatControls(WAV, '').bitDepths).toEqual([16, 24, 32])
    expect(formatControls(WAV, '').usesBitrate).toBe(false)
    const cbr = formatControls(MP3, '')
    expect([cbr.usesBitrate, cbr.usesQuality]).toEqual([true, false])
    const vbr = formatControls(MP3, 'vbr')
    expect([vbr.usesBitrate, vbr.usesQuality]).toEqual([false, true])
    expect(formatControls(undefined, '').bitrateModes).toEqual([])
    expect(bitrateModeLabel('abr')).toBe('Taxa média (ABR)')
  })

  it('lê instantes em segundos, com vírgula, ou de marcador, e recusa o resto', () => {
    expect(parseInstant('12,5')).toBe(12.5)
    expect(parseInstant(' marker:Introdução ')).toBe('marker:Introdução')
    expect(parseInstant('')).toBeUndefined()
    expect(parseInstant('abc')).toBeNull()
    expect(parseInstant('-3')).toBeNull()
  })

  it('o pedido leva só o que vale no modo e no formato', () => {
    const form = { ...emptyForm('audio/mp3'), loudness: 'podcast', bitrateK: '192', bitrateMode: 'cbr', group: 'cap', pauses: true, start: '3', tracks: ['NAR'] }
    expect(buildAudioExportRequest(form).request).toEqual({
      preset: 'audio/mp3',
      mode: 'mix',
      loudness: 'podcast',
      bitrate_mode: 'cbr',
      bitrate_k: 192,
    })
    expect(buildAudioExportRequest({ ...form, mode: 'regions', numbered: true }).request).toMatchObject({
      mode: 'regions',
      group: 'cap',
      pauses: true,
      numbered: true,
    })
    expect(buildAudioExportRequest({ ...form, mode: 'stems' }).request?.tracks).toEqual(['NAR'])
    expect(buildAudioExportRequest({ ...form, mode: 'stems', tracks: [] }).request).not.toHaveProperty('tracks')
  })

  it('a seleção pede o início, aceita marcador e confere a ordem', () => {
    const base = { ...emptyForm('audio/wav'), mode: 'selection' as const }
    expect(buildAudioExportRequest(base).error).toMatch(/onde o trecho começa/)
    expect(buildAudioExportRequest({ ...base, start: '5', end: '5' }).error).toMatch(/depois do início/)
    expect(buildAudioExportRequest({ ...base, start: 'x' }).error).toMatch(/segundos/)
    expect(buildAudioExportRequest({ ...base, start: 'marker:Fim' }).request).toMatchObject({ start: 'marker:Fim' })
    expect(buildAudioExportRequest({ ...base, start: '2', end: '9,5' }).request).toMatchObject({ start: 2, end: 9.5 })
  })

  it('sem formato ou com número inválido não há pedido', () => {
    expect(buildAudioExportRequest(emptyForm()).error).toMatch(/formato/)
    expect(buildAudioExportRequest({ ...emptyForm('audio/wav'), bitDepth: '24', sampleRate: '44100', channels: '1' }).request).toMatchObject({
      bit_depth: 24,
      sample_rate: 44100,
      channels: 1,
    })
    expect(buildAudioExportRequest({ ...emptyForm('audio/mp3'), bitrateK: 'muito' }).error).toMatch(/kbps/)
    expect(buildAudioExportRequest({ ...emptyForm('audio/mp3'), sampleRate: '-1' }).error).toMatch(/Hz/)
  })

  it('a pergunta de substituir cita os nomes e corta a lista longa', () => {
    expect(conflictQuestion(['C:\\out\\ep.mp3'])).toBe('O arquivo ep.mp3 já existe. Quer substituí-lo?')
    const many = Array.from({ length: 6 }, (_, i) => `/x/f${i}.wav`)
    expect(conflictQuestion(many)).toBe('Estes arquivos já existem: f0.wav, f1.wav, f2.wav, f3.wav e mais 2. Quer substituí-los?')
  })
})

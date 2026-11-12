import { describe, expect, it } from 'vitest'
import { approximateDuration, CAPABILITY_LABELS, capabilityLabel, capabilityList, capabilitySummary, previewEstimateText } from './personas'

const GESTURES_2D = ['nod', 'shake', 'tilt', 'wave']
const GESTURES_3D = ['nod', 'shake', 'tilt', 'wave', 'handup', 'index', 'ok', 'thumbup', 'thumbdown', 'side', 'shrug']
const EXPRESSIONS = ['neutral', 'happy', 'sad', 'surprised']

describe('nomes de expressões e gestos', () => {
  it('cobre todas as expressões e gestos dos dois motores', () => {
    for (const id of [...EXPRESSIONS, ...GESTURES_2D, ...GESTURES_3D]) expect(CAPABILITY_LABELS[id], id).toBeTruthy()
  })

  it('mostra o nome em português com o identificador da spec ao lado', () => {
    expect(capabilityLabel('happy')).toBe('alegre (happy)')
    expect(capabilityLabel('wave')).toBe('aceno com a mão (wave)')
    expect(capabilityLabel('nod')).toBe('sim com a cabeça (nod)')
  })

  it('um identificador desconhecido aparece como veio', () => {
    expect(capabilityLabel('moonwalk')).toBe('moonwalk')
    expect(capabilityList(['happy', 'moonwalk'])).toBe('alegre (happy), moonwalk')
  })
})

describe('a estimativa da prévia', () => {
  it('diz o tempo como gente: segundos, minutos ou horas', () => {
    expect(approximateDuration(40)).toBe('uns 40 s')
    expect(approximateDuration(660)).toBe('uns 11 min')
    expect(approximateDuration(6900)).toBe('uns 1 h 55 min')
  })

  it('fica vazia sem estimativa (motores rápidos)', () => {
    expect(previewEstimateText(undefined)).toBe('')
    expect(previewEstimateText({ seconds: null })).toBe('')
    expect(previewEstimateText({ seconds: 300, device_label: 'CPU (sem GPU integrada)' })).toBe(
      'A prévia leva uns 5 min neste computador (CPU (sem GPU integrada)), com ele livre.',
    )
  })

  it('a realista só tem a expressão da foto', () => {
    expect(capabilitySummary('realistic', ['neutral'], [])).toBe('Só a expressão da foto; sem gestos.')
    expect(capabilitySummary('2d', ['neutral'], ['nod'])).toBe('Expressões: neutra (neutral). Gestos: sim com a cabeça (nod).')
  })
})

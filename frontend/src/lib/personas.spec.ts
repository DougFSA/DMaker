import { describe, expect, it } from 'vitest'
import { CAPABILITY_LABELS, capabilityLabel, capabilityList } from './personas'

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

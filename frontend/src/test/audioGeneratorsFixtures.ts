/* O catálogo dos geradores de som de mentira (GET /api/audio-generators), com a forma que o servidor entrega. */
import type { AudioEffectParam, AudioGeneratorCatalog, AudioGeneratorInfo } from '@/api'

const param = (name: string, extra: Partial<AudioEffectParam> = {}): AudioEffectParam => ({
  name,
  label: name,
  kind: 'number',
  unit: '',
  default: 0,
  minimum: null,
  maximum: null,
  hint: '',
  options: [],
  ...extra,
})

export const toneInfo: AudioGeneratorInfo = {
  type: 'tone',
  label: 'Tom',
  audacity_name: 'Tone',
  summary: 'Uma onda de frequência fixa.',
  family: 'tons',
  default_duration: 1,
  has_natural_duration: false,
  parameters: [
    param('waveform', { label: 'Onda', kind: 'choice', default: 'sine', options: ['sine', 'square', 'sawtooth', 'square_bandlimited'] }),
    param('frequency_hz', { label: 'Frequência', unit: 'Hz', default: 440, minimum: 1, maximum: 20000 }),
    param('amplitude_db', { label: 'Amplitude', unit: 'dBFS', default: -2, minimum: -100, maximum: 0 }),
  ],
}

export const dtmfInfo: AudioGeneratorInfo = {
  type: 'dtmf',
  label: 'Tons DTMF',
  audacity_name: 'DTMF Tones',
  summary: 'O som das teclas de um telefone.',
  family: 'telefonia',
  default_duration: 0.75,
  has_natural_duration: true,
  parameters: [param('sequence', { label: 'Sequência', kind: 'text', default: '123' })],
}

export const rhythmInfo: AudioGeneratorInfo = {
  type: 'rhythm_track',
  label: 'Faixa de ritmo',
  audacity_name: 'Rhythm Track',
  summary: 'Um metrônomo.',
  family: 'ritmo',
  default_duration: 8,
  has_natural_duration: true,
  parameters: [
    param('tempo_bpm', { label: 'Andamento', unit: 'BPM', default: 120, minimum: 30, maximum: 300 }),
    param('accent_first', { label: 'Destacar o primeiro tempo', kind: 'boolean', default: true }),
  ],
}

export function audioGeneratorCatalog(): AudioGeneratorCatalog {
  return {
    generators: [toneInfo, dtmfInfo, rhythmInfo],
    item: [],
    target: 'audio.generated.N',
    track: 'SFX',
  }
}

/* Os efeitos de equalização de mentira dos testes: o mesmo formato que o servidor entrega no catálogo (domain/audio_effects/eq.py),
   com o passa-alta (uma escolha de opções numéricas), o EQ Gráfico (31 controles) e o EQ por Curva (pontos arrastáveis), mais uma
   predefinição embutida e uma salva pela pessoa. */
import type { AudioEffectCatalog, AudioEffectInfo, AudioEffectParam, EffectResponse } from '@/api'
import { audioEffectCatalog } from './audioEffectsFixtures'

function param(extra: Partial<AudioEffectParam> & Pick<AudioEffectParam, 'name' | 'label' | 'kind'>): AudioEffectParam {
  return { unit: '', default: null, minimum: null, maximum: null, hint: '', options: [], ...extra }
}

export const BAND_LABELS = [
  '20', '25', '31.5', '40', '50', '63', '80', '100', '125', '160', '200', '250', '315', '400', '500', '630',
  '800', '1k', '1.25k', '1.6k', '2k', '2.5k', '3.15k', '4k', '5k', '6.3k', '8k', '10k', '12.5k', '16k', '20k',
] // prettier-ignore

export const EQ_TYPES = ['highpass', 'graphic_eq', 'filter_curve_eq']

const lengthParam = param({ name: 'length', label: 'Tamanho do filtro', kind: 'integer', unit: 'amostras', default: 8191, minimum: 21, maximum: 8191 })

export function eqEffects(): AudioEffectInfo[] {
  return [
    {
      type: 'highpass',
      label: 'Passa-alta',
      audacity_name: 'High-Pass Filter',
      summary: 'Corta os graves abaixo da frequência.',
      changes_duration: false,
      has_response: true,
      parameters: [
        param({ name: 'slope_db', label: 'Inclinação', kind: 'choice', unit: 'dB/oitava', default: 6, options: ['6', '12', '18', '24', '30', '36', '42', '48'] }),
        param({ name: 'frequency_hz', label: 'Frequência de corte', kind: 'number', unit: 'Hz', default: 100, minimum: 1, maximum: 20000 }),
      ],
    },
    {
      type: 'graphic_eq',
      label: 'EQ gráfico',
      audacity_name: 'Graphic EQ',
      summary: '31 bandas de terço de oitava.',
      changes_duration: false,
      has_response: true,
      parameters: [
        param({ name: 'gains_db', label: 'Ganho por banda', kind: 'band_gains', unit: 'dB', default: new Array(31).fill(0) as unknown as number, minimum: -20, maximum: 20, options: BAND_LABELS }),
        param({ name: 'interpolation', label: 'Desenho da curva', kind: 'choice', default: 'bands', options: ['bands', 'cubic', 'cosine', 'linear'] }),
        lengthParam,
      ],
    },
    {
      type: 'filter_curve_eq',
      label: 'EQ por curva',
      audacity_name: 'Filter Curve EQ',
      summary: 'Curva livre por pontos.',
      changes_duration: false,
      has_response: true,
      parameters: [
        param({
          name: 'points',
          label: 'Pontos da curva',
          kind: 'freq_points',
          unit: 'Hz / dB',
          default: [
            { hz: 20, db: 0 },
            { hz: 20000, db: 0 },
          ] as unknown as number,
          minimum: -40,
          maximum: 40,
        }),
        param({ name: 'scale', label: 'Escala', kind: 'choice', default: 'log', options: ['log', 'linear'] }),
        param({ name: 'interpolation', label: 'Interpolação', kind: 'choice', default: 'cubic', options: ['cubic', 'cosine', 'linear'] }),
        lengthParam,
      ],
    },
  ]
}

/** O catálogo básico mais os três efeitos do EQ e duas predefinições (uma embutida, uma salva pela pessoa). */
export function eqCatalog(): AudioEffectCatalog {
  const base = audioEffectCatalog()
  return {
    ...base,
    effects: [...base.effects, ...eqEffects()],
    presets: [
      { id: 'rumble_100hz', label: 'Ronco de 100 Hz', summary: 'Passa-alta de 100 Hz.', origin: 'builtin', effects: [{ type: 'highpass', frequency_hz: 100, slope_db: 24 }] },
      { id: 'meu-corte', label: 'Meu corte', summary: '', origin: 'user', effects: [{ type: 'highpass', frequency_hz: 85, slope_db: 24 }] },
    ],
  }
}

/** Uma curva de resposta de mentira: sobe de -12 dB a 0 dB. */
export function responseCurve(): EffectResponse {
  return { hz: [20, 200, 2000, 20000], db: [-12, -6, 0, 0] }
}

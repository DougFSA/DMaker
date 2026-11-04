/* A análise de espectro de mentira dos testes: o mesmo formato da resposta de `POST /api/projects/{nome}/audio-analysis`
   para o analisador `spectrum`, com um tom de 1 kHz (pico de -6 dB) sobre um piso de -90 dB. */
import type { SpectrumAnalysis } from '@/api'

export function spectrumAnalysis(overrides: Partial<SpectrumAnalysis> = {}): SpectrumAnalysis {
  return {
    analyzer: 'spectrum',
    summary: 'Pico do espectro em 1000,0 Hz (-6,0 dB, perto de Si5).',
    warnings: [],
    source: 'Voz gravada 1 (tom.wav)',
    interval_s: [0, 2],
    algorithm: 'spectrum',
    window: 'hann',
    size: 4096,
    axis: 'log',
    sample_rate: 48000,
    bin_hz: 11.71875,
    peak_hz: 1000,
    peak_bin: 85,
    peak_db: -6,
    peak_note: 'Si5 +21 cents',
    peaks: [
      { frequency: 1000, level_db: -6, note: 'Si5 +21 cents' },
      { frequency: 2000, level_db: -60, note: 'Si6 +21 cents' },
    ],
    curve: {
      frequencies: [0, 100, 500, 1000, 1500, 5000, 24000],
      levels_db: [-90, -90, -80, -6, -80, -90, -90],
      points_total: 2049,
    },
    ...overrides,
  }
}

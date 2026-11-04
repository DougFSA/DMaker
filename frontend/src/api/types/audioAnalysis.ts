/* Tipos da análise de áudio (POST /api/projects/{nome}/audio-analysis, ui/audio_analysis_routes.py), com os nomes de
   campo do backend. A interface usa só o Espectro de Frequência, para desenhar o gráfico com o cursor. */

/** O andamento sugerido para a música (POST /api/projects/{nome}/audio-tempo/detect). A rota só lê e sugere: quem grava é o
 *  Salvar do editor. */
export interface TempoDetection {
  /** O arquivo analisado. */
  source: string
  bpm: number
  /** Onde cai o primeiro tempo dentro do arquivo, em segundos. */
  beat_offset: number
  /** De 0 a 1: quanto da energia dos ataques se repete nesse andamento. */
  confidence: number
  /** A metade e o dobro, para quando o ouvido marca outro tempo. */
  alternatives: number[]
  warnings: string[]
}

export type SpectrumAlgorithm = 'spectrum' | 'autocorrelation' | 'enhanced_autocorrelation' | 'cepstrum'

export type SpectrumWindow =
  | 'rectangular'
  | 'bartlett'
  | 'hamming'
  | 'hann'
  | 'blackman'
  | 'blackman_harris'
  | 'welch'
  | 'gaussian_2_5'
  | 'gaussian_3_5'
  | 'gaussian_4_5'

export type SpectrumAxis = 'linear' | 'log'

/** Os parâmetros do analisador `spectrum` que a interface deixa escolher. */
export interface SpectrumParams {
  algorithm: SpectrumAlgorithm
  window: SpectrumWindow
  /** Tamanho da FFT: potência de dois de 128 a 65536. */
  size: number
  axis: SpectrumAxis
}

export interface SpectrumRequest {
  /** O item como o catálogo dos efeitos o escreve (`audio.voiceover.0`), ou `output` (a saída final renderizada). */
  target: string
  start?: number | null
  end?: number | null
  params: SpectrumParams
  /** Quantos pontos a curva leva (o servidor guarda o pico de cada grupo). */
  points?: number
}

export interface SpectrumPeak {
  frequency: number
  level_db: number
  /** A nota mais próxima ("Lá4 +0 cents"), ou nulo. */
  note: string | null
}

/** A curva em ordem crescente de frequência; `points_total` é quantas divisões a FFT tem antes da redução. */
export interface SpectrumCurve {
  frequencies: number[]
  levels_db: number[]
  points_total: number
}

export interface SpectrumAnalysis extends SpectrumParams {
  analyzer: 'spectrum'
  summary: string
  warnings: string[]
  /** De onde veio o som ("Voz gravada 1 (entrevista.wav)"). */
  source: string
  /** O trecho analisado, em segundos do áudio do item. */
  interval_s: [number, number]
  notes?: string[]
  sample_rate: number
  /** A largura de uma divisão da FFT, em Hz. */
  bin_hz: number
  peak_hz: number
  peak_bin: number
  peak_db: number
  peak_note: string | null
  peaks: SpectrumPeak[]
  curve: SpectrumCurve
}

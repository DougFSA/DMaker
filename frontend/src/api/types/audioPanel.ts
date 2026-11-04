/* Tipos das rotas do painel Áudio (POST /api/projects/{nome}/audio-panel/wave, window e preview,
   ui/audio_panel_routes.py), com os nomes de campo do backend. */

/** A construção dos picos de um áudio: pronta, em andamento (a tela mostra o que já há e o andamento) ou falha. */
export type WaveState = 'ready' | 'building' | 'failed'

/** Como as colunas foram feitas: `peaks` pela pirâmide, `raw` das amostras de verdade (janela pequena) e `samples`
 *  quando a janela é tão pequena que as próprias amostras também vêm. */
export type WaveMode = 'peaks' | 'raw' | 'samples'

export interface AudioWaveClock {
  /** O instante da linha do tempo em que o item começa a soar. */
  start: number
  /** Quantos segundos do item passam por segundo da linha do tempo (a velocidade do clipe). */
  speed: number
}

export interface AudioWave {
  target: string
  label: string
  state: WaveState
  /** Identifica o som do item: muda com um efeito, um corte ou a troca do arquivo. */
  key: string
  /** O volume do item, que a janela para tocar já aplica. */
  gain: number
  /** O andamento (0 a 100) da etapa em curso. */
  percent: number
  /** O que está sendo feito ("Aplicando os efeitos", "Calculando a onda"). */
  stage: string
  error: string | null
  /** A duração do eixo, em segundos. */
  duration: number
  /** O instante do eixo em que o item começa a soar. */
  origin: number
  rate: number
  channels: number
  /** Quantas amostras o eixo tem por canal. */
  frames: number
  /** Nulo quando o item não tem lugar certo na linha do tempo (a faixa externa). */
  clock: AudioWaveClock | null
  notes: string[]
  start: number
  end: number
  columns: number
  /** Até onde a pirâmide já foi construída; o que vem depois está zerado e a tela pede de novo. */
  ready_until: number
  mode: WaveMode
  /** Por canal e por coluna: o mínimo e o máximo em inteiros de -127 a 127 (1,0 é 127). */
  mins: number[][]
  maxs: number[][]
  /** Por canal, as amostras de verdade (de -1 a 1); só no modo `samples`. */
  samples?: number[][]
}

export interface AudioWaveRequest {
  target: string
  start?: number
  end?: number | null
  columns: number
  /** Quantos segundos a rota espera uma construção terminar antes de responder com o andamento. */
  wait?: number
}

/** O som de uma janela pronto para tocar, e o que a prévia de um efeito diz sobre ele. */
export interface AudioWindow {
  /** O WAV de 16 bits. */
  data: ArrayBuffer
  /** Quantos segundos o WAV tem (o fim do áudio corta a janela). */
  seconds: number
  /** Só na prévia: ela é igual ao que o render faria? */
  exact: boolean
  /** Só na prévia: por que ela é aproximada. */
  note: string
}

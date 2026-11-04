/* A gravação ativada por som: decide, bloco a bloco, o que entra no arquivo. A gravação pausa quando o nível fica abaixo do
   limiar por mais que o tempo de espera, volta quando o som passa do limiar e guarda uns 300 ms de antes do som para o
   começo da fala não ser cortado. O arquivo final não tem os silêncios entre as falas.

   Os blocos de silêncio ficam guardados enquanto a espera corre: se o som volta a tempo, entram (uma pausa de respirar na
   frase fica como foi falada); se a espera acaba, só um pedaço curto de cauda é escrito e o resto é jogado fora.

   A decisão é uma função pura sobre os níveis por bloco (`gateDecisions`); o `SoundGate` é a mesma conta feita um bloco de
   cada vez, para a gravação ao vivo, e é ele que o teste compara com a conta pura. */

export interface SoundGateConfig {
  /** O nível (dBFS, de pico do bloco) a partir do qual há som. */
  thresholdDb: number
  /** Quanto tempo abaixo do limiar antes de pausar (ms): a pausa de respirar numa frase não corta a gravação. */
  waitMs: number
  /** Quanto som de antes da fala fica guardado (ms), para o começo não ser cortado. */
  prerollMs: number
  /** Quanto do silêncio depois da fala ainda entra no arquivo (ms), para o fim da palavra não ser cortado. */
  tailMs: number
  /** A duração de um bloco (ms). */
  blockMs: number
}

export const DEFAULT_GATE = { thresholdDb: -40, waitMs: 1500, prerollMs: 300, tailMs: 300 } as const

/** Quantos blocos cabem em `ms`, arredondando para cima (nunca guardar menos do que se pediu). */
const blocksIn = (ms: number, blockMs: number): number => Math.max(0, Math.ceil(ms / blockMs - 1e-9))

export interface GateStep {
  /** Os blocos a escrever agora, em ordem: pode vir mais de um (o pré-rolo ao abrir, ou a pausa curta que o som cobriu). */
  emit: number[]
  /** A gravação está escrevendo (dentro de uma fala ou da espera dela) depois deste bloco. */
  open: boolean
}

/** O estado da conta, um bloco de cada vez. */
export class SoundGate {
  private readonly waitBlocks: number
  private readonly prerollBlocks: number
  private readonly tailBlocks: number
  private isOpen = false
  /** Fechada: os últimos blocos, o pré-rolo. Aberta e abaixo do limiar: os blocos da espera, ainda não escritos. */
  private held: number[] = []
  private silent = 0
  private index = 0

  constructor(private readonly config: SoundGateConfig) {
    this.waitBlocks = blocksIn(config.waitMs, config.blockMs)
    this.prerollBlocks = blocksIn(config.prerollMs, config.blockMs)
    this.tailBlocks = blocksIn(config.tailMs, config.blockMs)
  }

  /** Recebe o nível do próximo bloco e diz o que escrever. */
  push(levelDb: number): GateStep {
    const block = this.index
    this.index += 1
    if (levelDb >= this.config.thresholdDb) {
      const emit = [...this.held, block]
      this.held = []
      this.silent = 0
      this.isOpen = true
      return { emit, open: true }
    }
    if (!this.isOpen) {
      this.held.push(block)
      if (this.held.length > this.prerollBlocks) this.held.splice(0, this.held.length - this.prerollBlocks)
      return { emit: [], open: false }
    }
    this.held.push(block)
    this.silent += 1
    if (this.silent <= this.waitBlocks) return { emit: [], open: true }
    // a espera acabou sem som: escreve só a cauda e passa a guardar o pré-rolo do que vem
    const tail = this.held.slice(0, this.tailBlocks)
    const rest = this.held.slice(this.tailBlocks) // o que sobra da espera: dele sai o pré-rolo, sem repetir a cauda
    this.held = this.prerollBlocks > 0 ? rest.slice(-this.prerollBlocks) : []
    this.isOpen = false
    this.silent = 0
    return { emit: tail, open: false }
  }

  /** O fim da gravação: se parou numa espera, a cauda dela ainda entra. */
  finish(): number[] {
    if (!this.isOpen) return []
    const tail = this.held.slice(0, this.tailBlocks)
    this.held = []
    this.isOpen = false
    return tail
  }
}

/**
 * Quais blocos entram no arquivo, dados os níveis de todos (dBFS, um por bloco). A mesma conta do `SoundGate`, de uma vez:
 * é o que o teste mede com níveis sintéticos e o que o `SoundGate` tem de reproduzir.
 */
export function gateDecisions(levelsDb: readonly number[], config: SoundGateConfig): boolean[] {
  const gate = new SoundGate(config)
  const kept = new Array<boolean>(levelsDb.length).fill(false)
  for (const level of levelsDb) for (const block of gate.push(level).emit) kept[block] = true
  for (const block of gate.finish()) kept[block] = true
  return kept
}

/** Os pedaços contínuos que entram: `[primeiro bloco, último bloco]` de cada fala gravada. */
export function keptRuns(kept: readonly boolean[]): Array<[number, number]> {
  const runs: Array<[number, number]> = []
  let start = -1
  kept.forEach((flag, index) => {
    if (flag && start < 0) start = index
    if (!flag && start >= 0) {
      runs.push([start, index - 1])
      start = -1
    }
  })
  if (start >= 0) runs.push([start, kept.length - 1])
  return runs
}

export interface SegmentRange {
  /** "de-ate" no formato que o backend lê (`parse_segments`), ou null para o vídeo inteiro. */
  value: string | null
  error: string | null
}

/** Lê os dois campos "do trecho / até o trecho" da prévia parcial; só um preenchido é erro.
 * Os números são os índices da validação (o primeiro trecho é o 0), os mesmos de `--segments` na CLI. */
export function segmentRange(from: string | number, to: string | number): SegmentRange {
  const start = String(from).trim()
  const end = String(to).trim()
  if (!start && !end) return { value: null, error: null }
  if (!start || !end) {
    return { value: null, error: 'Preencha os dois campos de trechos (início e fim) ou deixe ambos vazios.' }
  }
  const first = Number(start)
  const last = Number(end)
  if (!Number.isInteger(first) || !Number.isInteger(last) || first < 0 || last < first) {
    return {
      value: null,
      error: 'Use números inteiros a partir de 0, e o trecho final não pode vir antes do inicial.',
    }
  }
  return { value: `${first}-${last}`, error: null }
}

/* Cliente da análise de áudio (POST /api/projects/{nome}/audio-analysis, ui/audio_analysis_routes.py): o espectro de
   frequência de um item do projeto, que a interface desenha no gráfico com o cursor. A rota só lê: não grava nada. */
import { http } from './http'
import type { SpectrumAnalysis, SpectrumRequest } from './types/audioAnalysis'

/** Analisa o espectro do item (ou da saída final) e devolve a curva com o pico e a nota. */
export function analyzeSpectrum(project: string, request: SpectrumRequest): Promise<SpectrumAnalysis> {
  const { target, start, end, params, points } = request
  return http.post<SpectrumAnalysis>(`/api/projects/${encodeURIComponent(project)}/audio-analysis`, {
    analyzer: 'spectrum',
    target,
    start: start ?? null,
    end: end ?? null,
    params,
    ...(points ? { points } : {}),
  })
}

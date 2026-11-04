/* Cliente do painel Áudio (ui/audio_panel_routes.py): a onda de um item por zoom, uma janela do som para tocar e a
   prévia de um efeito ainda não gravado. Todas mandam a spec que o editor tem na tela, porque o que se vê e se ouve é o
   projeto em edição; nenhuma grava nada. */
import { http } from './http'
import type { AudioWave, AudioWaveRequest, AudioWindow } from './types/audioPanel'
import type { SpecDocument } from './types/editor'

const base = (project: string) => `/api/projects/${encodeURIComponent(project)}/audio-panel`

/** Os mínimos e máximos das colunas de uma janela do item (ou as amostras, no zoom máximo). */
export function fetchWave(project: string, spec: SpecDocument, request: AudioWaveRequest): Promise<AudioWave> {
  return http.post<AudioWave>(`${base(project)}/wave`, {
    spec,
    target: request.target,
    start: request.start ?? 0,
    end: request.end ?? null,
    columns: request.columns,
    ...(request.wait === undefined ? {} : { wait: request.wait }),
  })
}

async function windowOf(response: Response): Promise<AudioWindow> {
  return {
    data: await response.arrayBuffer(),
    seconds: Number(response.headers.get('X-Window-Seconds') ?? 0),
    exact: response.headers.get('X-Preview-Exact') !== '0',
    note: decodeURIComponent(response.headers.get('X-Preview-Note') ?? ''),
  }
}

/** O trecho [start, end) do item como soa, em WAV, para tocar sem baixar o áudio inteiro. */
export async function fetchWindow(
  project: string,
  spec: SpecDocument,
  target: string,
  start: number,
  end: number,
): Promise<AudioWindow> {
  return windowOf(await http.postResponse(`${base(project)}/window`, { spec, target, start, end }))
}

/** O mesmo trecho com o `effect` proposto ao fim da cadeia, sem gravar nada. */
export async function fetchEffectPreview(
  project: string,
  spec: SpecDocument,
  target: string,
  effect: Record<string, unknown>,
  start: number,
  end: number,
): Promise<AudioWindow> {
  return windowOf(await http.postResponse(`${base(project)}/preview`, { spec, target, effect, start, end }))
}

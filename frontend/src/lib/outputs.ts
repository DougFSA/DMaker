import type { OutputFile, RenderResult } from '@/api'
import type { PlayableVideo } from '@/components/outputs/VideoPlayerDialog.vue'
import { baseName, formatSizeMb } from './format'

export type OutputKindFilter = 'all' | 'final' | 'preview'

/** Saídas que combinam com a busca (nome, projeto ou formato) e com o tipo escolhido. */
export function filterOutputs(outputs: OutputFile[], query: string, kind: OutputKindFilter): OutputFile[] {
  const needle = query.trim().toLowerCase()
  return outputs.filter((output) => {
    if (kind !== 'all' && output.kind !== kind) return false
    if (!needle) return true
    return [output.name, output.project, output.preset ?? ''].some((field) => field.toLowerCase().includes(needle))
  })
}

export function playableFromOutput(output: OutputFile): PlayableVideo | null {
  if (!output.url) return null
  return {
    url: output.url,
    name: output.name,
    subtitle: [output.preset, output.kind === 'final' ? 'versão final' : 'prévia', formatSizeMb(output.size_mb)]
      .filter(Boolean)
      .join(' · '),
  }
}

export function playableFromRender(result: RenderResult): PlayableVideo | null {
  if (!result.output_url) return null
  return {
    url: result.output_url,
    name: baseName(result.output),
    subtitle: [result.preset, result.resolution, formatSizeMb(result.size_mb)].join(' · '),
  }
}

/** O resultado de um job de render (ou de exportação, que devolve uma lista) como RenderResult[]. */
export function renderResultsFromJob(result: unknown): RenderResult[] {
  const items = Array.isArray(result) ? result : [result]
  return items.filter(
    (item): item is RenderResult => !!item && typeof item === 'object' && 'output' in item && 'preset' in item,
  )
}

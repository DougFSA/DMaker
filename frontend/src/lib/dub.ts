/* Funções puras da tela de Dublagem: ler o que a pessoa digitou, montar as edições da tabela de falas, escrever o
   resumo do que o servidor fez e dizer como cada fala coube no tempo. Sem rede e sem DOM. */
import type {
  DubFitMode,
  DubProjectSummary,
  DubRenderResult,
  DubSegment,
  DubSegmentEdit,
  DubSegmentReport,
  DubSegmentStatus,
  DubSpeakerMode,
  DubStemsResult,
  DubStretchedSegment,
} from '@/api'
import { baseName } from './format'
import { formatSeconds, formatSecondsPrecise } from './speech'
import type { MediaEntry } from './media'
import type { ConfirmOptions } from '@/stores/confirm'

/** Passos de síntese do modo rascunho (`DRAFT_STEPS` do servidor): metade do tempo, voz um pouco menos refinada. */
export const DRAFT_STEPS = 8

/** Como a voz é escolhida: uma clonada por pessoa, uma por fala ou um clone só. Os rótulos são os da clássica. */
export const SPEAKER_MODE_OPTIONS: ReadonlyArray<{ value: DubSpeakerMode; label: string }> = [
  { value: 'per_speaker', label: 'Uma voz clonada por pessoa (separa quem fala)' },
  { value: 'per_segment', label: 'Clonar a voz em volta de cada fala' },
  { value: 'single', label: 'Um só clone para o arquivo todo' },
]

/** O que fazer quando a fala traduzida não cabe no tempo da original. */
export const FIT_MODE_OPTIONS: ReadonlyArray<{ value: DubFitMode; label: string }> = [
  { value: 'voz', label: 'Acelerar a voz' },
  { value: 'video', label: 'Esticar o vídeo (a voz fica natural)' },
  { value: 'misto', label: 'Misto (acelera um pouco e estica o resto)' },
]

/** O seletor devolve texto; só os modos conhecidos seguem para o servidor, o resto vira o padrão. */
export function speakerModeOf(value: string): DubSpeakerMode {
  return SPEAKER_MODE_OPTIONS.find((option) => option.value === value)?.value ?? 'per_speaker'
}

export function fitModeOf(value: string): DubFitMode {
  return FIT_MODE_OPTIONS.find((option) => option.value === value)?.value ?? 'voz'
}

/** Uma fala como a tabela a edita: o tempo e o original são só leitura; a tradução, o falante e a trava mudam. */
export interface DubRow {
  id: string
  start: number
  end: number
  original: string
  text: string
  locked: boolean
  speaker: string | null
}

/** O que a tabela edita de cada fala (o que `segmentEdits` envia ao salvar). */
export type EditableRow = Pick<DubRow, 'id' | 'text' | 'locked' | 'speaker'>

export function rowsFrom(segments: readonly DubSegment[]): DubRow[] {
  return segments.map((segment) => ({
    id: segment.id,
    start: segment.start,
    end: segment.end,
    original: segment.original,
    text: segment.text,
    locked: segment.locked,
    speaker: segment.speaker,
  }))
}

/** Termos separados por vírgula ou quebra de linha, sem vazios nem repetidos (sem diferenciar maiúsculas). */
export function parseGlossary(text: string): string[] {
  const seen = new Set<string>()
  return text
    .split(/[,\n]/)
    .map((term) => term.trim())
    .filter((term) => {
      const key = term.toLowerCase()
      if (!term || seen.has(key)) return false
      seen.add(key)
      return true
    })
}

/** O glossário do projeto de volta no campo de texto. */
export function formatGlossary(terms: readonly string[]): string {
  return terms.join(', ')
}

/** Volume da voz original por baixo, em dB: vazio é "sem voz original"; 18 e -18 valem -18 (nunca acima de zero). */
export function keepDbFrom(value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) return null
  return value === 0 ? 0 : -Math.abs(value)
}

/** Idiomas com a mesma língua de base ("pt" e "pt-BR") não dublam: o servidor recusa e a tela avisa antes. */
export function sameLanguage(a: string, b: string): boolean {
  const base = (code: string) => code.split('-')[0]!.toLowerCase()
  return base(a) === base(b)
}

/** As edições de cada fala para salvar: texto sem as pontas, trava e, só se escolhido, o falante. */
export function segmentEdits(rows: readonly EditableRow[]): DubSegmentEdit[] {
  return rows.map((row) => ({
    id: row.id,
    text: row.text.trim(),
    locked: !!row.locked,
    speaker: row.speaker || undefined,
  }))
}

/** O projeto salvo difere do que está na tabela? Só tradução, trava e falante contam (o resto não se edita na tabela). */
export function rowsChanged(segments: readonly DubSegment[], rows: readonly DubRow[]): boolean {
  if (segments.length !== rows.length) return true
  return segments.some((segment, index) => {
    const row = rows[index]!
    return (
      segment.id !== row.id ||
      segment.text.trim() !== row.text.trim() ||
      segment.locked !== row.locked ||
      (segment.speaker ?? null) !== (row.speaker ?? null)
    )
  })
}

/** O tempo de uma fala na tabela: "0,0 a 2,5 s". */
export function describeSpan(start: number, end: number): string {
  return `${formatSeconds(start)} a ${formatSeconds(end)} s`
}

/** A frase sobre o projeto aberto: quantas falas, o par de idiomas, o tradutor e o que fazer com os falantes. */
export function describeProject(project: Pick<DubProjectSummary, 'segments' | 'source_language' | 'target_language' | 'translator_model' | 'speakers'>): string {
  const model = project.translator_model ? ` Tradução: ${project.translator_model}.` : ''
  const people =
    project.speakers.length > 1
      ? ` ${project.speakers.length} falantes: troque o falante de uma fala se o programa errou; só essa fala é refeita.`
      : ''
  return `${project.segments.length} fala(s), ${project.source_language} para ${project.target_language}.${model}${people} Corrija o que precisar; as traduções travadas não mudam ao traduzir de novo.`
}

const STATUS_LABELS: Record<DubSegmentStatus, string> = {
  fits: 'cabe',
  advances: 'avança na pausa',
  squeezed: 'comprimida',
  stretched: 'vídeo esticado',
  overflow: 'não coube',
  empty: 'sem tradução',
}

export function statusLabel(status: DubSegmentStatus): string {
  return STATUS_LABELS[status] ?? status
}

/** A cor do selo (os tons do `AppBadge`): o que coube é verde, o que o programa ajustou é aviso e o que não coube é erro. */
export function statusTone(status: DubSegmentStatus): 'success' | 'info' | 'warning' | 'error' | 'neutral' {
  switch (status) {
    case 'fits':
      return 'success'
    case 'advances':
    case 'stretched':
      return 'info'
    case 'squeezed':
      return 'warning'
    case 'overflow':
      return 'error'
    default:
      return 'neutral'
  }
}

/** A situação de uma fala depois de gerar: "vídeo esticado 1,25x". A marca "nova" fica à parte (`isNewSpeech`). */
export function describeFit(report: Pick<DubSegmentReport, 'status' | 'video_stretch'>): string {
  const stretch = report.video_stretch > 1 ? ` ${formatSecondsPrecise(report.video_stretch)}x` : ''
  return `${statusLabel(report.status)}${stretch}`
}

/** A fala foi sintetizada agora (não veio do cache). */
export function isNewSpeech(report: Pick<DubSegmentReport, 'cached'>): boolean {
  return !report.cached
}

/** A frase sobre o vídeo esticado (vazia quando nada foi esticado): quantos trechos, quantos segundos a mais e o total. */
export function describeStretch(stretched: readonly DubStretchedSegment[], outputSeconds: number): string {
  if (stretched.length === 0) return ''
  const added = stretched.reduce((sum, item) => sum + item.added_seconds, 0)
  const total = outputSeconds ? ` O vídeo final tem ${formatSeconds(outputSeconds)} s.` : ''
  return ` Vídeo esticado em ${stretched.length} trecho(s), ${formatSeconds(added)} s a mais.${total}`
}

/** A frase do que a geração fez: quantas falas saíram agora, quantas vieram do cache e quanto tempo levou. */
export function describeResult(
  result: Pick<DubRenderResult, 'report' | 'regenerated' | 'timings' | 'stretched' | 'output_seconds'>,
): string {
  const seconds = Object.values(result.timings).reduce((sum, value) => sum + value, 0)
  const reused = result.report.length - result.regenerated
  const base = `${result.regenerated} fala(s) sintetizada(s) agora e ${reused} reaproveitada(s) do cache, em ${Math.round(seconds)} s.`
  return base + describeStretch(result.stretched, result.output_seconds)
}

/** A frase das trilhas exportadas, com o quanto a voz original ficava baixa no vídeo dublado. */
export function describeStems(result: Pick<DubStemsResult, 'files' | 'duration' | 'original_voice_db'>): string {
  const kept =
    result.original_voice_db === null
      ? ''
      : ` O vídeo dublado usa a voz original a ${result.original_voice_db} dB; a trilha dela vem sem atenuar.`
  return `Trilhas prontas (${result.files.join(', ')}), cada uma com ${formatSecondsPrecise(result.duration)} s.${kept}`
}

const VIDEO_SUFFIX = /\.(mp4|mov|mkv|webm|avi|m4v)$/i

/** A dublagem de um vídeo sai em vídeo e a de um áudio sai em áudio: o player certo depende da extensão da saída. */
export function mediaKindOf(path: string): 'audio' | 'video' {
  return VIDEO_SUFFIX.test(path) ? 'video' : 'audio'
}

const normalizePath = (path: string): string => path.replace(/\\/g, '/').toLowerCase()

/** A entrada da mídia do projeto aberto que é o arquivo dublado, para o "Usar no projeto" de uma dublagem reaberta. */
export function findProjectEntry(entries: readonly MediaEntry[], source: string): MediaEntry | null {
  const wanted = normalizePath(source)
  return entries.find((entry) => normalizePath(entry.path) === wanted) ?? null
}

/** O caminho da dublagem que já existe, no corpo do 409 de "preparar" (`{ detail, path }`); `null` se o corpo não o traz. */
export function existingProjectPath(body: unknown): string | null {
  if (!body || typeof body !== 'object' || !('path' in body)) return null
  const { path } = body as { path: unknown }
  return typeof path === 'string' && path ? path : null
}

/** A pergunta de preparar de novo uma dublagem que já existe: diz qual é e o que se perde (sem volta). */
export function overwriteConfirmation(existingPath: string | null): ConfirmOptions {
  const which = existingPath ? ` (${baseName(existingPath)})` : ''
  return {
    title: 'Preparar a dublagem de novo?',
    description: `Já existe uma dublagem preparada para este arquivo e este idioma${which}.`,
    warning:
      'Preparar de novo grava por cima dela e apaga as traduções que você revisou e as falas que você travou. Isso não tem como desfazer.',
    confirmLabel: 'Preparar de novo',
    cancelLabel: 'Manter a dublagem',
    tone: 'danger',
  }
}

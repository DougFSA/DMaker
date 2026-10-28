/* Regras da tela de lote que não dependem de componente: nomes, rótulos, contas de andamento. */
import type { BadgeTone } from '@/components/ui/AppBadge.vue'
import type { BatchIssue, BatchReport, BatchRow, BatchRowState, BatchStatus, BatchValidation } from '@/api'
import { baseName } from './format'

/** Nome do lote sugerido pelo arquivo da planilha: sem extensão, sem acento, em minúsculas com hifens. */
export function defaultBatchName(sheetPath: string): string {
  const stem = baseName(sheetPath).replace(/\.[^.]+$/, '')
  const slug = stem
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug || 'lote'
}

const ROW_TONES: Record<BatchRowState, BadgeTone> = {
  pending: 'neutral',
  running: 'accent',
  done: 'success',
  failed: 'error',
  invalid: 'warning',
}

export function rowTone(state: BatchRowState): BadgeTone {
  return ROW_TONES[state]
}

const STATUS_TONES: Record<BatchStatus, BadgeTone> = {
  running: 'accent',
  paused: 'warning',
  finished: 'success',
}

export function statusTone(status: BatchStatus): BadgeTone {
  return STATUS_TONES[status]
}

/** "coluna titulo: campo obrigatório vazio"; sem coluna, só a frase. */
export function issueText(issue: BatchIssue): string {
  return issue.field ? `coluna ${issue.field}: ${issue.message}` : issue.message
}

export function errorsOf(issues: BatchIssue[]): BatchIssue[] {
  return issues.filter((issue) => issue.level === 'erro')
}

export function warningsOf(issues: BatchIssue[]): BatchIssue[] {
  return issues.filter((issue) => issue.level === 'aviso')
}

/** O que a pessoa pode fazer com o lote validado: seguir, seguir sem as linhas ruins ou corrigir a planilha. */
export type StartPlan = 'all' | 'skip-invalid' | 'blocked'

export function startPlan(validation: BatchValidation): StartPlan {
  const sheetBlocked = errorsOf(validation.issues).length > 0
  if (sheetBlocked || validation.valid === 0) return 'blocked'
  return validation.invalid > 0 ? 'skip-invalid' : 'all'
}

/** Vídeos prontos sobre os que o lote tenta fazer (as linhas puladas não contam), de 0 a 100. */
export function batchPercent(report: Pick<BatchReport, 'done' | 'total'>): number {
  return report.total > 0 ? Math.round((report.done / report.total) * 100) : 0
}

/** Há o que retomar: vídeo pendente, que falhou ou que o servidor deu como parado no meio. */
export function canResume(report: BatchReport): boolean {
  return report.status !== 'running' && report.waiting + report.failed > 0
}

export function resumeLabel(report: BatchReport): string {
  return report.waiting > 0 ? 'Retomar' : 'Tentar de novo os que falharam'
}

/** Linhas que explicam por que um vídeo não saiu: a falha do render ou os problemas da planilha. */
export function reasonsOf(row: BatchRow): string[] {
  if (row.state === 'failed') return [row.error ?? 'O render falhou sem detalhe.']
  if (row.state === 'invalid') return errorsOf(row.issues).map(issueText)
  return []
}

export function outputUrl(path: string): string {
  return `/api/file?path=${encodeURIComponent(path.replace(/\\/g, '/'))}`
}

/** O resultado de um job de lote (o relatório em dicionário) quando é um; senão null. */
export function batchResultOf(result: unknown): Pick<BatchReport, 'name' | 'status' | 'summary' | 'failed'> | null {
  if (!result || typeof result !== 'object') return null
  const { name, status, summary, failed, rows } = result as Partial<BatchReport>
  if (typeof name !== 'string' || typeof summary !== 'string' || !Array.isArray(rows)) return null
  if (status !== 'running' && status !== 'paused' && status !== 'finished') return null
  return { name, status, summary, failed: typeof failed === 'number' ? failed : 0 }
}

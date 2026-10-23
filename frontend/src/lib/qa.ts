import type { QaFinding, QaLevel, QaReport } from '@/api'
import { formatClock } from './format'

const ORDER: QaLevel[] = ['erro', 'aviso', 'info']

export const QA_LEVEL_LABEL: Record<QaLevel, string> = {
  erro: 'Erro',
  aviso: 'Aviso',
  info: 'Informação',
}

export interface QaGroup {
  level: QaLevel
  label: string
  findings: QaFinding[]
}

/** Achados agrupados por gravidade (erros primeiro); níveis sem achado não aparecem. */
export function groupFindings(report: QaReport): QaGroup[] {
  return ORDER.map((level) => ({
    level,
    label: QA_LEVEL_LABEL[level],
    findings: report.findings.filter((finding) => finding.level === level),
  })).filter((group) => group.findings.length > 0)
}

export type QaVerdict = 'clean' | 'warnings' | 'errors'

/** Resumo de uma palavra para o selo do relatório. */
export function qaVerdict(report: QaReport): QaVerdict {
  if (report.findings.some((finding) => finding.level === 'erro')) return 'errors'
  if (report.findings.some((finding) => finding.level === 'aviso')) return 'warnings'
  return 'clean'
}

/** Onde no vídeo o achado aparece ("0:03"), ou vazio quando vale para o projeto todo. */
export function findingTime(finding: QaFinding): string {
  return finding.at == null ? '' : formatClock(finding.at)
}

/** "0 erros, 7 avisos" para o cabeçalho do cartão. */
export function qaCounts(report: QaReport): string {
  const count = (level: QaLevel) => report.findings.filter((finding) => finding.level === level).length
  const errors = count('erro')
  const warnings = count('aviso')
  const infos = count('info')
  return [
    `${errors} ${errors === 1 ? 'erro' : 'erros'}`,
    `${warnings} ${warnings === 1 ? 'aviso' : 'avisos'}`,
    `${infos} ${infos === 1 ? 'informação' : 'informações'}`,
  ].join(', ')
}

import { describe, expect, it } from 'vitest'
import type { BatchIssue, BatchReport, BatchRow, BatchValidation } from '@/api'
import {
  batchPercent,
  batchResultOf,
  canResume,
  defaultBatchName,
  errorsOf,
  issueText,
  outputUrl,
  reasonsOf,
  resumeLabel,
  rowTone,
  startPlan,
  statusTone,
  warningsOf,
} from './batches'

function validation(overrides: Partial<BatchValidation> = {}): BatchValidation {
  return {
    template: 'stories-medlycare',
    name_column: 'titulo',
    headers: ['titulo'],
    columns: { matched: { titulo: 'titulo' }, unused: [], missing: [] },
    issues: [],
    rows: [],
    total: 5,
    valid: 5,
    invalid: 0,
    ok: true,
    text: '',
    ...overrides,
  }
}

function row(overrides: Partial<BatchRow> = {}): BatchRow {
  return {
    index: 1,
    line: 2,
    title: 'Dica um',
    state: 'pending',
    state_label: 'Pendente',
    project: 'semana-dica-um',
    output: null,
    duration_s: null,
    render_s: null,
    error: null,
    warnings: [],
    issues: [],
    ...overrides,
  }
}

function report(overrides: Partial<BatchReport> = {}): BatchReport {
  return {
    name: 'semana',
    template: 'stories-medlycare',
    status: 'paused',
    status_label: 'Pausado',
    preview: false,
    output_dir: 'D:/output/semana',
    total: 5,
    done: 2,
    failed: 0,
    skipped: 0,
    waiting: 3,
    summary: '2 de 5 vídeo(s) pronto(s), 3 esperando',
    rows: [],
    ...overrides,
  }
}

describe('nome do lote', () => {
  it('vem do arquivo da planilha, sem extensão nem acento', () => {
    expect(defaultBatchName('D:/Planilhas/Série Procedimentos 2026.xlsx')).toBe('serie-procedimentos-2026')
    expect(defaultBatchName('C:\\dados\\semana_01.csv')).toBe('semana-01')
    expect(defaultBatchName('???.csv')).toBe('lote')
  })
})

describe('problemas da planilha', () => {
  const error: BatchIssue = { line: 3, field: 'imagem', message: 'arquivo não encontrado', level: 'erro' }
  const warning: BatchIssue = { line: null, field: null, message: 'coluna ignorada', level: 'aviso' }

  it('diz a coluna quando há uma', () => {
    expect(issueText(error)).toBe('coluna imagem: arquivo não encontrado')
    expect(issueText(warning)).toBe('coluna ignorada')
  })

  it('separa erros de avisos', () => {
    expect(errorsOf([error, warning])).toEqual([error])
    expect(warningsOf([error, warning])).toEqual([warning])
  })
})

describe('o que fazer depois da validação', () => {
  it('segue com tudo quando nenhuma linha tem problema', () => {
    expect(startPlan(validation())).toBe('all')
  })

  it('pede confirmação para seguir sem as linhas com problema', () => {
    expect(startPlan(validation({ valid: 4, invalid: 1, ok: false }))).toBe('skip-invalid')
  })

  it('bloqueia quando nenhuma linha serve ou a planilha inteira tem erro', () => {
    expect(startPlan(validation({ valid: 0, invalid: 5, ok: false }))).toBe('blocked')
    const sheetError: BatchIssue = { line: null, field: 'imagem', message: 'falta a coluna', level: 'erro' }
    expect(startPlan(validation({ issues: [sheetError], ok: false }))).toBe('blocked')
  })
})

describe('andamento do lote', () => {
  it('conta os prontos sobre os que o lote tenta fazer', () => {
    expect(batchPercent(report())).toBe(40)
    expect(batchPercent(report({ total: 0, done: 0 }))).toBe(0)
  })

  it('só oferece retomar quando não está rodando e sobra algo a fazer', () => {
    expect(canResume(report())).toBe(true)
    expect(canResume(report({ status: 'running' }))).toBe(false)
    expect(canResume(report({ status: 'finished', waiting: 0, failed: 0 }))).toBe(false)
    expect(canResume(report({ status: 'finished', waiting: 0, failed: 1 }))).toBe(true)
  })

  it('chama de retomar o que falta e de tentar de novo o que só falhou', () => {
    expect(resumeLabel(report())).toBe('Retomar')
    expect(resumeLabel(report({ waiting: 0, failed: 2 }))).toBe('Tentar de novo os que falharam')
  })

  it('escolhe a cor de cada estado', () => {
    expect(rowTone('done')).toBe('success')
    expect(rowTone('failed')).toBe('error')
    expect(rowTone('invalid')).toBe('warning')
    expect(statusTone('running')).toBe('accent')
    expect(statusTone('paused')).toBe('warning')
  })
})

describe('por que um vídeo não saiu', () => {
  it('mostra o erro do render ou os problemas da linha pulada', () => {
    expect(reasonsOf(row({ state: 'failed', error: 'RuntimeError: sem espaço' }))).toEqual(['RuntimeError: sem espaço'])
    expect(reasonsOf(row({ state: 'failed' }))).toEqual(['O render falhou sem detalhe.'])
    const issues: BatchIssue[] = [
      { line: 4, field: 'imagem', message: 'arquivo não encontrado', level: 'erro' },
      { line: 4, field: null, message: 'um aviso', level: 'aviso' },
    ]
    expect(reasonsOf(row({ state: 'invalid', issues }))).toEqual(['coluna imagem: arquivo não encontrado'])
    expect(reasonsOf(row({ state: 'done' }))).toEqual([])
  })
})

describe('arquivos e resultado do job', () => {
  it('monta a URL do vídeo com o caminho codificado', () => {
    expect(outputUrl('D:\\output\\semana\\dica um.mp4')).toBe(
      `/api/file?path=${encodeURIComponent('D:/output/semana/dica um.mp4')}`,
    )
  })

  it('reconhece o relatório de lote no resultado de um job', () => {
    const result = { ...report({ failed: 1 }), rows: [] }
    expect(batchResultOf(result)).toEqual({
      name: 'semana',
      status: 'paused',
      summary: '2 de 5 vídeo(s) pronto(s), 3 esperando',
      failed: 1,
    })
    expect(batchResultOf({ output: 'a.mp4', preset: 'x' })).toBeNull()
    expect(batchResultOf(null)).toBeNull()
    expect(batchResultOf({ ...result, status: 'cancelled' })).toBeNull()
  })
})

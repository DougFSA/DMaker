import { describe, expect, it } from 'vitest'
import type {
  CutReport,
  OutputFile,
  LookInfo,
  ProjectListItem,
  QaReport,
  TemplateInfo,
  TransitionInfo,
} from '@/api'
import { effectChips, filterLooks, specSnippet as lookSnippet } from './looks'
import { cutsSummary, defaultCutName, formatCutTime, reasonCounts, reasonTone } from './cuts'
import { baseName, formatClock, formatDuration, formatRelative, formatSizeMb } from './format'
import { filterOutputs, renderResultsFromJob } from './outputs'
import { buildTemplateParams, defaultParamValues, filterProjects, missingRequiredParams, parseList } from './projects'
import { findingTime, groupFindings, qaCounts, qaVerdict } from './qa'
import { segmentRange } from './render'
import { filterTransitions, specSnippet } from './transitions'

describe('format', () => {
  it('formata relógio e duração', () => {
    expect(formatClock(65)).toBe('1:05')
    expect(formatClock(3723)).toBe('1:02:03')
    expect(formatDuration(7)).toBe('7 s')
    expect(formatDuration(185)).toBe('3 min 05 s')
  })

  it('formata tamanho em MB e GB', () => {
    expect(formatSizeMb(0.54)).toBe('0,5 MB')
    expect(formatSizeMb(2048)).toBe('2 GB')
  })

  it('diz há quanto tempo, em português', () => {
    const now = 1_000_000_000_000
    const seconds = now / 1000
    expect(formatRelative(seconds - 10, now)).toBe('agora há pouco')
    expect(formatRelative(seconds - 300, now)).toBe('há 5 min')
    expect(formatRelative(seconds - 7200, now)).toBe('há 2 h')
    expect(formatRelative(seconds - 86400, now)).toBe('há 1 dia')
  })

  it('pega o nome do arquivo com / ou \\', () => {
    expect(baseName('D:/a/b/c.mp4')).toBe('c.mp4')
    expect(baseName('D:\\a\\b\\c.mp4')).toBe('c.mp4')
  })
})

describe('projetos', () => {
  const list: ProjectListItem[] = [
    { name: 'Reel-Lançamento', spec_path: 'a', preset: 'instagram/reels', brand: 'medlycare' },
    { name: 'casamento', spec_path: 'b', preset: 'youtube/video', brand: null },
  ]

  it('busca sem diferenciar maiúsculas nem acentos, em nome, formato e marca', () => {
    expect(filterProjects(list, 'lancamento').map((p) => p.name)).toEqual(['Reel-Lançamento'])
    expect(filterProjects(list, 'YOUTUBE').map((p) => p.name)).toEqual(['casamento'])
    expect(filterProjects(list, 'medly').map((p) => p.name)).toEqual(['Reel-Lançamento'])
    expect(filterProjects(list, '  ')).toHaveLength(2)
  })

  const template: TemplateInfo = {
    name: 't',
    description: '',
    summary: '',
    params: {
      titulo: { description: '', type: 'text', default: 'Oi', required: false },
      print: { description: '', type: 'path', default: null, required: true },
      fotos: { description: '', type: 'paths', default: null, required: false },
      ligado: { description: '', type: 'bool', default: null, required: false },
    },
  }

  it('começa pelos padrões do template, com bool desligado', () => {
    expect(defaultParamValues(template)).toEqual({
      titulo: 'Oi',
      print: undefined,
      fotos: undefined,
      ligado: false,
    })
  })

  it('manda só os parâmetros preenchidos e acusa os obrigatórios que faltam', () => {
    const values = { titulo: '', print: undefined, fotos: [], ligado: false }
    expect(buildTemplateParams(template, values)).toEqual({ ligado: false })
    expect(missingRequiredParams(template, values)).toEqual(['print'])
    expect(missingRequiredParams(template, { ...values, print: 'C:/x.png' })).toEqual([])
  })

  it('lê uma lista separada por vírgula', () => {
    expect(parseList(' a, b ,, c ')).toEqual(['a', 'b', 'c'])
  })
})

describe('qa', () => {
  const report: QaReport = {
    text: '',
    project: 'p',
    preset: 'instagram/reels',
    total: 17,
    checks: [],
    findings: [
      { level: 'info', where: 'a', message: 'x', at: null },
      { level: 'aviso', where: 'b', message: 'y', at: 3 },
      { level: 'aviso', where: 'c', message: 'z', at: null },
    ],
  }

  it('agrupa por gravidade, erros primeiro, sem grupos vazios', () => {
    expect(groupFindings(report).map((g) => [g.level, g.findings.length])).toEqual([
      ['aviso', 2],
      ['info', 1],
    ])
  })

  it('resume o veredito e a contagem', () => {
    expect(qaVerdict(report)).toBe('warnings')
    expect(qaVerdict({ ...report, findings: [] })).toBe('clean')
    expect(qaVerdict({ ...report, findings: [{ level: 'erro', where: '', message: '', at: null }] })).toBe('errors')
    expect(qaCounts(report)).toBe('0 erros, 2 avisos, 1 informação')
  })

  it('mostra o instante do achado quando existe', () => {
    expect(findingTime({ level: 'aviso', where: '', message: '', at: 3 })).toBe('0:03')
    expect(findingTime({ level: 'aviso', where: '', message: '', at: null })).toBe('')
  })
})

describe('render parcial', () => {
  it('vazio é o vídeo inteiro', () => {
    expect(segmentRange('', '')).toEqual({ value: null, error: null })
  })

  it('monta de-ate a partir de 0', () => {
    expect(segmentRange('0', '3')).toEqual({ value: '0-3', error: null })
    expect(segmentRange(2, 2)).toEqual({ value: '2-2', error: null })
  })

  it('recusa só um campo, fim antes do início e não inteiros', () => {
    expect(segmentRange('1', '').error).toBeTruthy()
    expect(segmentRange('5', '2').error).toBeTruthy()
    expect(segmentRange('1.5', '3').error).toBeTruthy()
    expect(segmentRange('-1', '3').error).toBeTruthy()
  })
})

describe('cortes automáticos', () => {
  const report = {
    removed_percent: 27.4,
    duration_before_s: 120,
    duration_after_s: 87.1,
    counts: { silence: 14, filler: 1, repetition: 0 },
  } as unknown as CutReport

  it('conta os cortes aplicados por motivo, no singular e no plural', () => {
    expect(reasonCounts(report.counts)).toBe('14 pausas, 1 vício')
    expect(reasonCounts({ repetition: 2 })).toBe('2 repetições')
    expect(reasonCounts({})).toBe('')
  })

  it('resume o antes e o depois com a porcentagem', () => {
    expect(cutsSummary(report)).toBe('2:00 para 1:27 (27% a menos)')
  })

  it('mostra o instante com décimos', () => {
    expect(formatCutTime(83.44)).toBe('01:23.4')
    expect(formatCutTime(5.04)).toBe('00:05.0')
  })

  it('sugere o nome do projeto pelo arquivo', () => {
    expect(defaultCutName('D:/Vídeos/entrevista final.mp4')).toBe('entrevista final-corte')
    expect(defaultCutName('C:\\gravacao.mov')).toBe('gravacao-corte')
  })

  it('dá um tom por motivo', () => {
    expect(reasonTone('filler')).toBe('warning')
    expect(reasonTone('silence')).toBe('neutral')
  })
})

describe('saídas', () => {
  const outputs = [
    { name: 'demo__instagram-reels.mp4', project: 'demo', preset: 'instagram/reels', kind: 'final' },
    { name: 'outro__youtube-video__preview.mp4', project: 'outro', preset: 'youtube/video', kind: 'preview' },
  ] as OutputFile[]

  it('filtra por tipo e busca', () => {
    expect(filterOutputs(outputs, '', 'all')).toHaveLength(2)
    expect(filterOutputs(outputs, '', 'preview').map((o) => o.project)).toEqual(['outro'])
    expect(filterOutputs(outputs, 'REELS', 'all').map((o) => o.project)).toEqual(['demo'])
  })

  it('lê o resultado de render ou de exportação do job', () => {
    const result = { output: 'a.mp4', preset: 'x' }
    expect(renderResultsFromJob(result)).toHaveLength(1)
    expect(renderResultsFromJob([result, result])).toHaveLength(2)
    expect(renderResultsFromJob(null)).toEqual([])
  })
})


describe('transições', () => {
  const list: TransitionInfo[] = [
    { name: 'whippan', kind: 'motion', summary: 'Chicote com borrão de movimento.' },
    { name: 'wipeleft', kind: 'xfade', summary: 'Uma cortina corre para a esquerda.' },
  ]

  it('filtra por tipo e busca em nome e descrição sem diferenciar maiúsculas', () => {
    expect(filterTransitions(list, '', 'all')).toHaveLength(2)
    expect(filterTransitions(list, '', 'motion').map((t) => t.name)).toEqual(['whippan'])
    expect(filterTransitions(list, 'CORTINA', 'all').map((t) => t.name)).toEqual(['wipeleft'])
    expect(filterTransitions(list, 'whip', 'xfade')).toEqual([])
    expect(filterTransitions(list, '  ', 'all')).toHaveLength(2)
  })

  it('monta o trecho de spec sem curva quando é a linear', () => {
    expect(specSnippet('fade', 'linear')).toBe('"transition": { "type": "fade", "duration": 0.5 }')
    expect(specSnippet('whippan', 'spring')).toBe(
      '"transition": { "type": "whippan", "duration": 0.5, "curve": "spring" }',
    )
  })
})

describe('looks', () => {
  const list: LookInfo[] = [
    {
      name: 'cinema',
      summary: 'Verde-azulado nas sombras e grão fino.',
      source: 'padrão',
      effects: { vignette: 0.35, grain: 0.2 },
    },
    { name: 'clinica', summary: 'Cores limpas da marca.', source: 'marca', effects: {} },
  ]

  it('filtra pela origem e busca em nome e descrição sem diferenciar maiúsculas', () => {
    expect(filterLooks(list, '', 'all')).toHaveLength(2)
    expect(filterLooks(list, '', 'marca').map((l) => l.name)).toEqual(['clinica'])
    expect(filterLooks(list, 'GRÃO', 'all').map((l) => l.name)).toEqual(['cinema'])
    expect(filterLooks(list, 'cinema', 'marca')).toEqual([])
    expect(filterLooks(list, '  ', 'all')).toHaveLength(2)
  })

  it('lista só os efeitos ligados, na ordem da galeria, com a quantidade de cada um', () => {
    expect(effectChips(list[0]!)).toEqual([
      { name: 'vignette', label: 'vinheta', amount: 0.35 },
      { name: 'grain', label: 'grão', amount: 0.2 },
    ])
    expect(effectChips(list[1]!)).toEqual([])
  })

  it('monta o trecho de spec do projeto inteiro', () => {
    expect(lookSnippet('pb-contraste')).toBe('"look": "pb-contraste"')
  })
})

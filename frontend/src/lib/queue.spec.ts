import { describe, expect, it } from 'vitest'
import { queueItem, queueView } from '@/test/queueServer'
import {
  ACTION_FAILURES,
  ACTION_HINTS,
  ACTION_LABELS,
  actionsFor,
  canClearFinished,
  DANGEROUS_ACTIONS,
  describeProgress,
  firstLine,
  formatAudioLength,
  hasErrorDetails,
  itemMeta,
  moveLimits,
  narrationSummary,
  queueSummary,
  showsProgress,
  stateTone,
} from './queue'

describe('actionsFor', () => {
  it('cada estado oferece só o que o servidor aceita, na ordem dos botões', () => {
    expect(actionsFor('pending')).toEqual(['pause', 'cancel', 'up', 'down'])
    expect(actionsFor('running')).toEqual(['pause', 'cancel'])
    expect(actionsFor('paused')).toEqual(['resume', 'cancel', 'up', 'down'])
    expect(actionsFor('failed')).toEqual(['retry', 'remove'])
    expect(actionsFor('cancelled')).toEqual(['retry', 'remove'])
    expect(actionsFor('done')).toEqual(['remove'])
  })

  it('um estado desconhecido não oferece botão nenhum', () => {
    expect(actionsFor('arquivado')).toEqual([])
  })

  it('só o item que não roda pode ser removido, e só o que espera pode subir ou descer', () => {
    expect(actionsFor('running')).not.toContain('remove')
    for (const state of ['running', 'failed', 'cancelled', 'done']) expect(actionsFor(state)).not.toContain('up')
  })

  it('toda ação tem rótulo, dica e frase de falha, e só cancelar e remover são de perigo', () => {
    const everyAction = ['pause', 'resume', 'cancel', 'up', 'down', 'retry', 'remove'] as const
    for (const action of everyAction) {
      expect(ACTION_LABELS[action], action).not.toBe('')
      expect(ACTION_HINTS[action], action).not.toBe('')
      expect(ACTION_FAILURES[action], action).toMatch(/^Não consegui /)
    }
    expect([...DANGEROUS_ACTIONS].sort()).toEqual(['cancel', 'remove'])
  })
})

describe('stateTone e showsProgress', () => {
  it('cada estado tem a sua cor de selo', () => {
    expect(stateTone('running')).toBe('accent')
    expect(stateTone('paused')).toBe('warning')
    expect(stateTone('done')).toBe('success')
    expect(stateTone('failed')).toBe('error')
    expect(stateTone('pending')).toBe('neutral')
    expect(stateTone('cancelled')).toBe('neutral')
    expect(stateTone('arquivado')).toBe('neutral')
  })

  it('a barra aparece enquanto o item espera, roda ou está pausado', () => {
    expect(['pending', 'running', 'paused'].every(showsProgress)).toBe(true)
    expect(['done', 'failed', 'cancelled'].some(showsProgress)).toBe(false)
  })
})

describe('formatAudioLength', () => {
  it('escreve horas, minutos ou segundos como o servidor', () => {
    expect(formatAudioLength(40)).toBe('40 s')
    expect(formatAudioLength(125)).toBe('2 min')
    expect(formatAudioLength(7500)).toBe('2 h 05 min')
    expect(formatAudioLength(3600)).toBe('1 h 00 min')
    expect(formatAudioLength(0)).toBe('0 s')
  })
})

describe('firstLine e hasErrorDetails', () => {
  it('tira o nome da exceção e fica só com a primeira linha', () => {
    expect(firstLine('VoiceNotFoundError: A voz "x" não existe.\nTraceback...')).toBe('A voz "x" não existe.')
    expect(firstLine('Falhou sem nome de exceção')).toBe('Falhou sem nome de exceção')
    expect(firstLine(null)).toBe('')
  })

  it('o erro de várias linhas deixa abrir o texto inteiro', () => {
    expect(hasErrorDetails('uma linha só')).toBe(false)
    expect(hasErrorDetails('Erro\n  at algum.lugar')).toBe(true)
    expect(hasErrorDetails('uma linha só\n')).toBe(false)
    expect(hasErrorDetails(null)).toBe(false)
  })
})

describe('describeProgress', () => {
  it('em andamento diz o capítulo, a fala e quanto falta', () => {
    const item = queueItem({
      state: 'running',
      chapter: 2,
      chapters_total: 5,
      utterance: 7,
      utterances: 30,
      eta_label: '12 min',
    })
    expect(describeProgress(item)).toBe('capítulo 2 de 5, fala 7 de 30 · faltam cerca de 12 min')
  })

  it('com um capítulo só, não repete "capítulo 1 de 1"', () => {
    const item = queueItem({ state: 'running', chapter: 1, chapters_total: 1, utterance: 3, utterances: 9, eta_label: null })
    expect(describeProgress(item)).toBe('fala 3 de 9')
  })

  it('uma estimativa que arredonda para 0 s não aparece', () => {
    const item = queueItem({ state: 'pending', chapters_total: 1, eta_label: '0 s', eta_seconds: 0 })
    expect(describeProgress(item)).toBe('Aguardando a vez · 1 capítulo')
    expect(queueSummary(queueView([item], { eta_label: '0 s', eta_seconds: 0 })).text).toBe('1 item')
  })

  it('antes da primeira fala o item está preparando o roteiro', () => {
    expect(describeProgress(queueItem({ state: 'running', chapter: 0, eta_label: '40 s' }))).toBe(
      'Preparando o roteiro · faltam cerca de 40 s',
    )
  })

  it('pendente, pausado, pronto, cancelado e com falha', () => {
    expect(describeProgress(queueItem({ state: 'pending', chapters_total: 3, eta_label: '2 min' }))).toBe(
      'Aguardando a vez · 3 capítulos · faltam cerca de 2 min',
    )
    expect(describeProgress(queueItem({ state: 'pending', chapters_total: 1, eta_label: null }))).toBe(
      'Aguardando a vez · 1 capítulo',
    )
    expect(describeProgress(queueItem({ state: 'paused', percent: 40, chapters_total: 2 }))).toBe('Pausado em 40% · 2 capítulos')
    expect(describeProgress(queueItem({ state: 'done', chapters_total: 2, duration_s: 7500 }))).toBe(
      'Pronto · 2 capítulos · 2 h 05 min de áudio',
    )
    expect(describeProgress(queueItem({ state: 'done', chapters_total: 1, duration_s: null }))).toBe('Pronto · 1 capítulo')
    expect(describeProgress(queueItem({ state: 'cancelled', percent: 55 }))).toBe('Cancelado em 55%')
    expect(describeProgress(queueItem({ state: 'failed', error: 'RuntimeError: sem memória\nlinha 2' }))).toBe('sem memória')
    expect(describeProgress(queueItem({ state: 'failed', error: null }))).toBe('Falhou')
  })
})

describe('itemMeta', () => {
  it('diz de onde veio o roteiro, o formato e se é rascunho', () => {
    const file = queueItem({
      source: { kind: 'file', name: 'curso.docx' },
      options: { voice: null, language: null, speed: 1, brand: null, draft: true, format: 'mp3' },
    })
    expect(itemMeta(file)).toEqual(['arquivo', 'curso.docx', 'rascunho', 'MP3'])
    expect(itemMeta(queueItem())).toEqual(['texto', 'texto', 'WAV'])
  })
})

describe('queueSummary', () => {
  it('fila vazia', () => {
    expect(queueSummary(queueView())).toEqual({ text: 'A fila está vazia.', warning: null })
  })

  it('conta os itens e diz quanto falta para esvaziar', () => {
    const view = queueView([queueItem({ id: 'a' }), queueItem({ id: 'b' })])
    expect(queueSummary(view)).toEqual({ text: '2 itens · tempo estimado para esvaziar: 80 s', warning: null })
    expect(queueSummary(queueView([queueItem()])).text).toBe('1 item · tempo estimado para esvaziar: 40 s')
  })

  it('sem item esperando, não fala de tempo', () => {
    const view = queueView([queueItem({ state: 'done' })])
    expect(queueSummary(view).text).toBe('1 item')
  })

  it('avisa quando há o que narrar e o servidor diz que não tem executor', () => {
    const view = queueView([queueItem()], { worker: false })
    expect(queueSummary(view).warning).toContain('Nenhum executor ativo')
  })

  it('não avisa se há executor, se algo já está rodando ou se não há o que narrar', () => {
    expect(queueSummary(queueView([queueItem()], { worker: true })).warning).toBeNull()
    expect(queueSummary(queueView([queueItem({ state: 'running' })], { worker: false })).warning).toBeNull()
    expect(queueSummary(queueView([queueItem({ state: 'paused' })], { worker: false })).warning).toBeNull()
  })

  it('uma resposta sem o campo "worker" não é motivo de alarme', () => {
    const view = queueView([queueItem()])
    delete view.worker
    expect(queueSummary(view).warning).toBeNull()
  })
})

describe('canClearFinished', () => {
  it('só há o que limpar com item pronto ou cancelado; os que falharam ficam', () => {
    expect(canClearFinished(queueView([queueItem({ state: 'done' })]))).toBe(true)
    expect(canClearFinished(queueView([queueItem({ state: 'cancelled' })]))).toBe(true)
    expect(canClearFinished(queueView([queueItem({ state: 'failed' }), queueItem({ id: 'b', state: 'running' })]))).toBe(false)
    expect(canClearFinished(queueView())).toBe(false)
  })
})

describe('moveLimits', () => {
  it('entre os que esperam, o primeiro não sobe e o último não desce', () => {
    const limits = moveLimits([
      queueItem({ id: 'a', state: 'running' }),
      queueItem({ id: 'b', state: 'pending' }),
      queueItem({ id: 'c', state: 'done' }),
      queueItem({ id: 'd', state: 'paused' }),
      queueItem({ id: 'e', state: 'pending' }),
    ])
    expect(limits).toEqual({
      b: { up: false, down: true },
      d: { up: true, down: true },
      e: { up: true, down: false },
    })
  })

  it('um item só que espera não sobe nem desce', () => {
    expect(moveLimits([queueItem({ id: 'a' })])).toEqual({ a: { up: false, down: false } })
  })

  it('quem não espera não tem limite', () => {
    expect(moveLimits([queueItem({ id: 'a', state: 'done' })])).toEqual({})
  })
})

describe('narrationSummary', () => {
  it('diz a voz, o idioma e a velocidade que valem para o roteiro importado', () => {
    expect(narrationSummary('Dora (feminina)', 'Português', 1.25)).toBe('Dora (feminina) · Português · velocidade 1,25x')
  })

  it('sem escolha, diz o que o servidor faz no lugar', () => {
    expect(narrationSummary(null, null, 1)).toBe('Voz automática do motor · idioma da voz · velocidade 1,00x')
  })
})

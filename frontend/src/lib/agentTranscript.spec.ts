import { describe, expect, it } from 'vitest'
import type { TranscriptEntry } from '@/api'
import { dropAfterLastUser, pendingConfirmation, reduceEvent, type StreamEvent } from './agent'
import { itemsFromTranscript } from './agentTranscript'

const TRANSCRIPT: TranscriptEntry[] = [
  { kind: 'user', id: 'e1', text: 'Valida o projeto meu-video', at: '2026-10-30T12:00:00.000+00:00' },
  { kind: 'kits', id: 'e2', kits: ['editing'], method: 'keywords' },
  { kind: 'thinking', id: 'e3', text: 'Preciso validar.' },
  {
    kind: 'tool',
    id: 'e4',
    name: 'validate_project',
    arguments: { name_or_path: 'meu-video' },
    state: 'done',
    detail: '{"name": "meu-video"}',
    result: '{"name": "meu-video", "ok": true}',
  },
  { kind: 'answer', id: 'e5', text: 'O projeto está válido.', interrupted: false },
]

describe('itemsFromTranscript', () => {
  it('desenha a transcrição salva com os mesmos itens do turno ao vivo', () => {
    const items = itemsFromTranscript(TRANSCRIPT)

    expect(items.map((item) => item.kind)).toEqual(['user', 'kits', 'thinking', 'tool', 'answer'])
    expect(items[0]).toEqual({ kind: 'user', id: 'e1', text: 'Valida o projeto meu-video' })
    expect(items[3]).toMatchObject({ kind: 'tool', state: 'done', percent: null, label: '', result: '{"name": "meu-video", "ok": true}' })
    expect(items[2]).toMatchObject({ kind: 'thinking', streaming: false })
    expect(items[4]).toMatchObject({ kind: 'answer', interrupted: false, streaming: false })
  })

  it('a resposta parada guarda a marca de interrompida', () => {
    const items = itemsFromTranscript([{ kind: 'answer', id: 'e2', text: 'O cinema,', interrupted: true }])
    expect(items[0]).toMatchObject({ kind: 'answer', text: 'O cinema,', interrupted: true })
  })

  it('a confirmação sem resposta fica "não confirmada" e não pede clique', () => {
    const items = itemsFromTranscript([
      {
        kind: 'confirmation',
        id: 'e2',
        confirmation_id: 'cf1',
        tool: 'render_project',
        question: 'Posso gerar o vídeo final?',
        type: 'action',
        state: 'unconfirmed',
      },
    ])

    expect(items[0]).toMatchObject({ kind: 'confirmation', confirmationId: 'cf1', state: 'unconfirmed' })
    expect(pendingConfirmation(items)).toBeNull()
  })

  it('a ferramenta interrompida pelo fechamento do DMaker mantém o estado e o motivo', () => {
    const items = itemsFromTranscript([
      {
        kind: 'tool',
        id: 'e2',
        name: 'render_project',
        arguments: {},
        state: 'interrupted',
        detail: 'Interrompida porque o DMaker foi fechado.',
        result: '',
      },
    ])
    expect(items[0]).toMatchObject({ state: 'interrupted', detail: 'Interrompida porque o DMaker foi fechado.' })
  })

  it('os avisos viram avisos e o erro vira o item de erro', () => {
    const items = itemsFromTranscript([
      { kind: 'notice', id: 'e1', level: 'info', code: 'history_trimmed', text: 'Tirei 1 turno antigo.' },
      { kind: 'notice', id: 'e2', level: 'warning', code: 'unfinished', text: 'Esta resposta não terminou.' },
      { kind: 'notice', id: 'e3', level: 'error', code: 'error', text: 'TimeoutError: o modelo não respondeu' },
    ])

    expect(items).toEqual([
      { kind: 'notice', id: 'e1', level: 'info', code: 'history_trimmed', text: 'Tirei 1 turno antigo.' },
      { kind: 'notice', id: 'e2', level: 'warning', code: 'unfinished', text: 'Esta resposta não terminou.' },
      { kind: 'error', id: 'e3', text: 'TimeoutError: o modelo não respondeu' },
    ])
  })

  it('uma entrada de um tipo desconhecido é pulada, e o resto da conversa abre', () => {
    const future = { kind: 'chart', id: 'e9' } as unknown as TranscriptEntry
    const items = itemsFromTranscript([TRANSCRIPT[0]!, future, TRANSCRIPT[4]!])
    expect(items.map((item) => item.kind)).toEqual(['user', 'answer'])
  })

  it('recarregar no meio do turno: o que vem depois da mensagem sai e o turno reenviado refaz tudo sem duplicar', () => {
    const saved = itemsFromTranscript(TRANSCRIPT.slice(0, 4)) // user, kits, thinking, tool em andamento
    const base = dropAfterLastUser(saved)
    expect(base.map((item) => item.kind)).toEqual(['user'])

    let counter = 0
    const nextId = () => `n${(counter += 1)}`
    const replay: StreamEvent[] = [
      { kind: 'start', t: 0, description: 'agente' },
      { kind: 'triage', t: 0, kits: ['editing'], method: 'keywords' },
      { kind: 'thinking', t: 1, text: 'Preciso validar.' },
      { kind: 'tool_call', t: 2, name: 'validate_project', arguments: {} },
    ]
    const rebuilt = replay.reduce((items, event) => reduceEvent(items, event, base.length, nextId), base)

    expect(rebuilt.map((item) => item.kind)).toEqual(['user', 'kits', 'thinking', 'tool'])
  })
})

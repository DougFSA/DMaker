import { describe, expect, it } from 'vitest'
import type { AgentKit } from '@/api'
import {
  confirmationLabels,
  errorSummary,
  kitTitle,
  pendingConfirmation,
  reduceEvent,
  summarizeArguments,
  type ChatItem,
  type StreamEvent,
  type ToolItem,
} from './agent'

function ids(): () => string {
  let n = 0
  return () => `i${(n += 1)}`
}

/** Aplica os eventos em ordem, como o store faz com o SSE. */
function play(events: StreamEvent[], start: ChatItem[] = [], base = start.length): ChatItem[] {
  const nextId = ids()
  return events.reduce((items, event) => reduceEvent(items, event, base, nextId), start)
}

const USER: ChatItem = { kind: 'user', id: 'u1', text: 'renderiza o x' }

describe('reduceEvent: o roteiro de um pedido', () => {
  it('conta o kit escolhido, a ferramenta, o resultado e a resposta, nessa ordem', () => {
    const items = play(
      [
        { kind: 'start', t: 0, description: 'agente' },
        { kind: 'triage', t: 1, kits: ['editing'], method: 'keywords' },
        { kind: 'tool_call', t: 2, name: 'presets', arguments: { platform: 'instagram' } },
        { kind: 'tool_result', t: 3, name: 'presets', result: '[{"id": "instagram/reels"}]\nsegunda linha' },
        { kind: 'answer', t: 4, text: 'Os formatos são Reels e Shorts.' },
        { kind: 'end', t: 5, status: 'done', error: null, result: {} },
      ],
      [USER],
    )

    expect(items.map((item) => item.kind)).toEqual(['user', 'kits', 'tool', 'answer'])
    const tool = items[2] as ToolItem
    expect(tool.state).toBe('done')
    expect(tool.detail).toBe('[{"id": "instagram/reels"}]') // só a primeira linha do resultado
  })

  it('marca como erro o resultado que começa com "erro:"', () => {
    const items = play([
      { kind: 'tool_call', t: 0, name: 'validate_project', arguments: {} },
      { kind: 'tool_result', t: 1, name: 'validate_project', result: 'erro: falta o argumento' },
    ])
    expect((items[0] as ToolItem).state).toBe('error')
  })

  it('uma chamada barrada fica barrada mesmo com o resultado que vem depois', () => {
    const items = play([
      { kind: 'tool_call', t: 0, name: 'render_project', arguments: { name_or_path: 'x' } },
      { kind: 'tool_blocked', t: 1, name: 'render_project', reason: 'O usuário não autorizou: Posso gerar o vídeo final?' },
      { kind: 'tool_result', t: 2, name: 'render_project', result: 'O usuário não autorizou: Posso gerar o vídeo final?' },
    ])
    const tool = items[0] as ToolItem
    expect(tool.state).toBe('blocked')
    expect(tool.detail).toContain('não autorizou')
  })

  it('o andamento ao vivo atualiza a ferramenta que está rodando', () => {
    const items = play([
      { kind: 'tool_call', t: 0, name: 'render_project', arguments: {} },
      { kind: 'tool_progress', t: 1, name: 'render_project', status: 'running', progress: { percent: 40, label: 'encode' } },
      { kind: 'tool_progress', t: 2, name: 'render_project', status: 'running', progress: { percent: 70 } },
    ])
    const tool = items[0] as ToolItem
    expect(tool).toMatchObject({ state: 'running', percent: 70, label: 'encode' })
  })

  it('duas chamadas da mesma ferramenta não se misturam', () => {
    const items = play([
      { kind: 'tool_call', t: 0, name: 'quick_edit', arguments: { preview: true } },
      { kind: 'tool_result', t: 1, name: 'quick_edit', result: 'prévia' },
      { kind: 'tool_call', t: 2, name: 'quick_edit', arguments: { preview: false } },
      { kind: 'tool_progress', t: 3, name: 'quick_edit', status: 'running', progress: { percent: 10 } },
    ])
    expect((items[0] as ToolItem).state).toBe('done')
    expect(items[1]).toMatchObject({ state: 'running', percent: 10 })
  })

  it('a confirmação pede o clique e guarda a resposta', () => {
    const asked = play([
      { kind: 'confirmation_request', t: 0, id: 'c1', tool: 'render_project', question: 'Posso gerar o vídeo final?', type: 'action' },
    ])
    expect(pendingConfirmation(asked)?.confirmationId).toBe('c1')

    const answered = reduceEvent(asked, { kind: 'confirmation_answered', t: 1, id: 'c1', approved: false }, 0, ids())
    expect(answered[0]).toMatchObject({ kind: 'confirmation', state: 'refused' })
    expect(pendingConfirmation(answered)).toBeNull()
  })

  it('reconectar reenvia tudo: o "start" volta o turno ao ponto inicial em vez de duplicar', () => {
    const first = play([{ kind: 'triage', t: 0, kits: ['voice'], method: 'keywords' }, { kind: 'tool_call', t: 1, name: 'list_voices', arguments: {} }], [USER])
    const replay = play(
      [
        { kind: 'start', t: 0, description: 'agente' },
        { kind: 'triage', t: 0, kits: ['voice'], method: 'keywords' },
      ],
      first,
      1,
    )
    expect(replay.map((item) => item.kind)).toEqual(['user', 'kits'])
  })

  it('um job que terminou com erro vira uma mensagem de erro curta', () => {
    const items = play([
      { kind: 'end', t: 9, status: 'error', error: 'RuntimeError: sem espaço em disco\n  File "x.py", line 3', result: null },
    ])
    expect(items).toEqual([{ kind: 'error', id: 'i1', text: 'RuntimeError: sem espaço em disco' }])
  })

  it('eventos que não mudam a conversa (log, progresso do job, modelo respondendo) são ignorados', () => {
    const items = play([
      { kind: 'log', t: 0, message: 'etapa' },
      { kind: 'model_reply', t: 1, seconds: 2, tool_calls: 0 },
      { kind: 'thinking', t: 2, text: 'hum' },
    ])
    expect(items).toEqual([])
  })
})

describe('apresentação', () => {
  it('resume os argumentos numa linha e corta valores longos', () => {
    const text = summarizeArguments({ name_or_path: 'meu-video', preview: true, paths: ['a.mp4'], texto: 'x'.repeat(100) })
    expect(text).toContain('name_or_path=meu-video')
    expect(text).toContain('preview=true')
    expect(text).toContain('paths=["a.mp4"]')
    expect(text).toContain('…')
    expect(summarizeArguments({})).toBe('')
  })

  it('mostra o título do kit e, se o kit é desconhecido, o próprio nome', () => {
    const kits: AgentKit[] = [{ name: 'editing', title: 'Edição e render', description: '', tools: 10 }]
    expect(kitTitle('editing', kits)).toBe('Edição e render')
    expect(kitTitle('novo', kits)).toBe('novo')
  })

  it('a autorização de voz diz o que a pessoa está afirmando', () => {
    expect(confirmationLabels('voice_consent')).toEqual({ yes: 'O dono da voz autorizou', no: 'Não autorizou' })
    expect(confirmationLabels('action')).toEqual({ yes: 'Confirmar', no: 'Não fazer' })
  })

  it('o resumo do erro pega a mensagem e não o traceback', () => {
    expect(errorSummary(null)).toBe('O agente parou sem uma resposta.')
    expect(errorSummary('ValueError: nome ruim\n  File "a.py"\nTraceback')).toBe('ValueError: nome ruim')
  })
})

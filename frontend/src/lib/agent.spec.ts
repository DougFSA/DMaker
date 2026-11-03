import { describe, expect, it } from 'vitest'
import type { AgentKit } from '@/api'
import {
  confirmationLabels,
  dropAfterLastUser,
  errorSummary,
  isInterrupted,
  kitTitle,
  noticeTitle,
  pendingConfirmation,
  reduceEvent,
  stageOf,
  STOPPED,
  STOPPED_BEFORE_START,
  summarizeArguments,
  type AnswerItem,
  type ChatItem,
  type StreamEvent,
  type ThinkingItem,
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
const END_DONE: StreamEvent = { kind: 'end', t: 9, status: 'done', error: null, result: {} }

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
    expect(tool.result).toContain('segunda linha')
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

  it('eventos que não mudam a conversa (log, modelo respondendo, etapa) são ignorados', () => {
    const items = play([
      { kind: 'log', t: 0, message: 'etapa' },
      { kind: 'model_reply', t: 1, seconds: 2, tool_calls: 0 },
      { kind: 'status', t: 2, stage: 'reading', label: 'Lendo o pedido' },
    ])
    expect(items).toEqual([])
  })

  it('o resultado completo da ferramenta fica guardado, cortado em 800 caracteres', () => {
    const items = play([
      { kind: 'tool_call', t: 0, name: 'qa', arguments: {} },
      { kind: 'tool_result', t: 1, name: 'qa', result: `linha um\n${'x'.repeat(900)}` },
    ])
    const tool = items[0] as ToolItem
    expect(tool.detail).toBe('linha um')
    expect(tool.result).toHaveLength(800)
    expect(tool.result.endsWith('…')).toBe(true)
  })
})

describe('reduceEvent: a resposta em fluxo', () => {
  it('os trechos da resposta crescem num balão só e a resposta final o fecha', () => {
    const streaming = play([
      { kind: 'answer_delta', t: 0, text: 'O cin' },
      { kind: 'answer_delta', t: 1, text: 'ema,' },
    ])
    expect(streaming).toEqual([{ kind: 'answer', id: 'i1', text: 'O cinema,', interrupted: false, streaming: true }])

    const done = reduceEvent(streaming, { kind: 'answer', t: 2, text: 'O cinema, como arte.' }, 0, ids())
    expect(done).toEqual([{ kind: 'answer', id: 'i1', text: 'O cinema, como arte.', interrupted: false, streaming: false }])
  })

  it('o raciocínio chega à parte, antes da resposta, e o texto final o substitui', () => {
    const items = play([
      { kind: 'status', t: 0, stage: 'thinking', label: 'Pensando' },
      { kind: 'thinking_delta', t: 1, text: 'O usuário quer ' },
      { kind: 'thinking_delta', t: 2, text: 'um resumo.' },
      { kind: 'answer_delta', t: 3, text: 'Aqui vai.' },
      { kind: 'model_reply', t: 4, seconds: 3, tool_calls: 0 },
      { kind: 'thinking', t: 5, text: 'O usuário quer um resumo.\n' },
      { kind: 'answer', t: 6, text: 'Aqui vai.' },
    ])

    expect(items.map((item) => item.kind)).toEqual(['thinking', 'answer'])
    expect(items[0]).toMatchObject({ text: 'O usuário quer um resumo.\n', streaming: false })
    expect(items[1]).toMatchObject({ text: 'Aqui vai.', streaming: false })
  })

  it('um motor sem fluxo entrega o raciocínio e a resposta inteiros, na mesma ordem', () => {
    const items = play([
      { kind: 'thinking', t: 0, text: 'penso' },
      { kind: 'answer', t: 1, text: 'pronto' },
    ])
    expect(items.map((item) => item.kind)).toEqual(['thinking', 'answer'])
    expect((items[0] as ThinkingItem).streaming).toBe(false)
  })

  it('o texto que veio antes de uma chamada de ferramenta não vira resposta', () => {
    const items = play([
      { kind: 'answer_delta', t: 0, text: 'Vou olhar o projeto.' },
      { kind: 'model_reply', t: 1, seconds: 1, tool_calls: 1 },
      { kind: 'tool_call', t: 2, name: 'validate_project', arguments: {} },
      { kind: 'tool_result', t: 3, name: 'validate_project', result: 'ok' },
      { kind: 'answer_delta', t: 4, text: 'Está válido.' },
      { kind: 'model_reply', t: 5, seconds: 1, tool_calls: 0 },
      { kind: 'answer', t: 6, text: 'Está válido.' },
    ])
    expect(items.map((item) => item.kind)).toEqual(['tool', 'answer'])
    expect((items[1] as AnswerItem).text).toBe('Está válido.')
  })

  it('a resposta de um turno anterior não é confundida com a do turno novo', () => {
    const before: ChatItem[] = [
      USER,
      { kind: 'answer', id: 'a0', text: 'resposta de antes', interrupted: false, streaming: false },
      { kind: 'user', id: 'u2', text: 'e agora?' },
    ]
    const items = play([{ kind: 'answer', t: 0, text: 'resposta nova' }], before, 3)
    expect(items.map((item) => item.id)).toEqual(['u1', 'a0', 'u2', 'i1'])
    expect((items[1] as AnswerItem).text).toBe('resposta de antes')
  })

  it('o aviso de aparo entra na conversa com o texto do servidor', () => {
    const items = play([{ kind: 'history_trimmed', t: 0, turns: 2, text: 'Tirei 2 turnos antigos.' }])
    expect(items).toEqual([{ kind: 'notice', id: 'i1', level: 'info', code: 'history_trimmed', text: 'Tirei 2 turnos antigos.' }])
  })
})

describe('reduceEvent: Parar é uma parada normal', () => {
  it('a resposta parcial fica marcada como interrompida e o fim cancelado não vira erro', () => {
    const items = play(
      [
        { kind: 'answer_delta', t: 0, text: 'O cinema,' },
        { kind: 'answer', t: 1, text: 'O cinema,', interrupted: true },
        { kind: 'end', t: 2, status: 'cancelled', error: null, result: { answer: 'O cinema,', interrupted: true } },
      ],
      [USER],
    )
    expect(items.map((item) => item.kind)).toEqual(['user', 'answer'])
    expect(items[1]).toMatchObject({ text: 'O cinema,', interrupted: true, streaming: false })
  })

  it('parar antes de qualquer texto deixa só o aviso, sem balão vazio', () => {
    const items = play(
      [
        { kind: 'answer', t: 0, text: '', interrupted: true },
        { kind: 'end', t: 1, status: 'cancelled', error: null, result: { answer: '', interrupted: true } },
      ],
      [USER],
    )
    expect(items.map((item) => item.kind)).toEqual(['user', 'notice'])
    expect(items[1]).toMatchObject({ code: 'interrupted', text: STOPPED_BEFORE_START })
  })

  it('parar tira da tela o balão vazio que estava começando', () => {
    const items = play([
      { kind: 'answer_delta', t: 0, text: ' ' },
      { kind: 'answer', t: 1, text: '', interrupted: true },
    ])
    expect(items.map((item) => item.kind)).toEqual(['notice'])
  })

  it('um cancelamento sem resposta parcial ainda é uma parada, com um aviso', () => {
    const items = play([{ kind: 'end', t: 0, status: 'cancelled', error: null, result: null }])
    expect(items).toEqual([{ kind: 'notice', id: 'i1', level: 'info', code: 'interrupted', text: STOPPED }])
  })

  it('o erro no meio da resposta fecha o que estava chegando e mostra a mensagem', () => {
    const items = play([
      { kind: 'thinking_delta', t: 0, text: 'penso' },
      { kind: 'answer_delta', t: 1, text: 'meio' },
      { kind: 'end', t: 2, status: 'error', error: 'ChatStreamError: a conexão caiu', result: null },
    ])
    expect(items.map((item) => item.kind)).toEqual(['thinking', 'answer', 'error'])
    expect(items.some((item) => 'streaming' in item && item.streaming)).toBe(false)
  })

  it('o fim bem-sucedido não acrescenta nada', () => {
    expect(play([END_DONE], [USER])).toEqual([USER])
  })

  it('reconhece o resultado de uma parada pela chave interrupted', () => {
    expect(isInterrupted({ answer: 'x', interrupted: true })).toBe(true)
    expect(isInterrupted({ answer: 'x' })).toBe(false)
    expect(isInterrupted(null)).toBe(false)
  })
})

describe('etapa do agente', () => {
  it('lê a etapa de um evento status e ignora os outros', () => {
    expect(stageOf({ kind: 'status', t: 0, stage: 'tool', label: 'Chamando a ferramenta render_project', tool: 'render_project' })).toEqual({
      stage: 'tool',
      label: 'Chamando a ferramenta render_project',
      tool: 'render_project',
    })
    expect(stageOf({ kind: 'status', t: 0, stage: 'reading', label: 'Lendo o pedido' })).toEqual({ stage: 'reading', label: 'Lendo o pedido' })
    expect(stageOf(END_DONE)).toBeNull()
  })
})

describe('dropAfterLastUser', () => {
  it('guarda a conversa só até a última mensagem da pessoa', () => {
    const items: ChatItem[] = [
      USER,
      { kind: 'answer', id: 'a1', text: 'oi', interrupted: false, streaming: false },
      { kind: 'user', id: 'u2', text: 'e agora?' },
      { kind: 'kits', id: 'k2', kits: ['editing'], method: 'keywords' },
      { kind: 'tool', id: 't2', name: 'x', arguments: {}, state: 'running', detail: '', result: '', percent: null, label: '' },
    ]
    expect(dropAfterLastUser(items).map((item) => item.id)).toEqual(['u1', 'a1', 'u2'])
  })

  it('sem mensagem da pessoa, não sobra nada', () => {
    expect(dropAfterLastUser([{ kind: 'notice', id: 'n1', level: 'info', code: 'unfinished', text: 'x' }])).toEqual([])
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

  it('cada aviso tem um título curto', () => {
    expect(noticeTitle('history_trimmed')).toBe('Conversa aparada')
    expect(noticeTitle('unfinished')).toBe('Resposta incompleta')
    expect(noticeTitle('interrupted')).toBe('Resposta parada')
  })

  it('o resumo do erro pega a mensagem e não o traceback', () => {
    expect(errorSummary(null)).toBe('O agente parou sem uma resposta.')
    expect(errorSummary('ValueError: nome ruim\n  File "a.py"\nTraceback')).toBe('ValueError: nome ruim')
  })
})

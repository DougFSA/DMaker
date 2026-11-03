import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory } from 'vue-router'
import ConfirmHost from '@/components/ui/ConfirmHost.vue'
import type { StreamEvent } from '@/lib/agent'
import { createAppRouter } from '@/router'
import { OPEN_CONVERSATION_KEY } from '@/stores/agent'
import { useConfirmStore } from '@/stores/confirm'
import { detail, MODELS, MODELS_WITH_GEMMA, QWEN, STATUS, stubAgentServer, type AgentServer } from '@/test/agentServer'
import { FakeEventSource } from '@/test/fetch'
import { reply } from '@/test/routedFetch'
import AgentView from './AgentView.vue'

let server: AgentServer
let wrapper: VueWrapper | null = null

/** A tela com o diálogo de confirmação que a casca do app monta (apagar e enviar com memória curta perguntam antes). */
async function mountView(): Promise<VueWrapper> {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agente')
  await router.isReady()
  const Host = defineComponent({ render: () => [h(AgentView), h(ConfirmHost)] })
  wrapper = mount(Host, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  server = stubAgentServer({ 'GET /api/state': { version: '1', presets: [], brands: [], projects: [] } })
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const emit = (event: StreamEvent) => FakeEventSource.latest().emit(event)
const END_DONE: StreamEvent = { kind: 'end', t: 9, status: 'done', error: null, result: {} }

async function sendMessage(view: VueWrapper, text: string): Promise<void> {
  await view.find('#agent-message').setValue(text)
  await view.find('form.composer').trigger('submit')
  await flushPromises()
}

const buttonNamed = (view: VueWrapper, label: string) => view.findAll('button').find((button) => button.text() === label)
const dialog = () => document.body.querySelector('[role="alertdialog"]')

/** Responde ao diálogo de confirmação como a pessoa faria. */
async function answerDialog(accepted: boolean): Promise<void> {
  useConfirmStore().answer(accepted)
  await flushPromises()
}

describe('tela Agente: abrir', () => {
  it('abre com o servidor do modelo, o modelo escolhido, exemplos de pedido e os kits', async () => {
    const view = await mountView()

    expect(view.text()).toContain('Ollama')
    expect((view.findAll('select')[0]!.element as HTMLSelectElement).value).toBe('gpt-oss:20b')
    expect(view.text()).toContain('O que você quer fazer?')
    expect(view.findAll('.example')).toHaveLength(4)
    expect(view.find('details.kit-list').text()).toContain('Voz e narração')
  })

  it('clicar num exemplo preenche a mensagem', async () => {
    const view = await mountView()
    await view.find('.example').trigger('click')

    expect((view.find('#agent-message').element as HTMLTextAreaElement).value).toContain('Faz um reel')
  })

  it('mostra o que fazer quando o servidor do modelo está parado e não deixa enviar', async () => {
    server = stubAgentServer({ 'GET /api/agent/status': { ...STATUS, reachable: false, model_installed: false }, 'GET /api/agent/models': reply(503, { detail: 'fora do ar' }) })
    const view = await mountView()

    expect(view.find('.problem [role="alert"]').text()).toContain('O modelo local não está respondendo em http://127.0.0.1:11434')
    await view.find('#agent-message').setValue('oi')
    expect(view.find('form.composer button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  it('avisa que falta o modelo e manda olhar o doctor', async () => {
    server = stubAgentServer({ 'GET /api/agent/models': { ...MODELS, models: [QWEN] } })
    const view = await mountView()

    expect(view.find('.problem [role="alert"]').text()).toContain('dmaker doctor --offline')
  })

  it('volta à conversa lembrada e desenha a transcrição salva com os mesmos componentes do turno ao vivo', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    server = stubAgentServer({}, [
      detail({
        transcript: [
          { kind: 'user', id: 'e1', text: 'Valida o projeto meu-video', at: '2026-10-30T12:00:00.000+00:00' },
          { kind: 'kits', id: 'e2', kits: ['editing'], method: 'keywords' },
          { kind: 'thinking', id: 'e3', text: 'Preciso validar.' },
          { kind: 'tool', id: 'e4', name: 'validate_project', arguments: { name_or_path: 'meu-video' }, state: 'done', detail: 'ok', result: 'ok' },
          { kind: 'confirmation', id: 'e5', confirmation_id: 'cf9', tool: 'render_project', question: 'Posso gerar o vídeo final?', type: 'action', state: 'unconfirmed' },
          { kind: 'notice', id: 'e6', level: 'warning', code: 'unfinished', text: 'Esta resposta não terminou porque o DMaker foi fechado no meio dela.' },
        ],
      }),
    ])
    const view = await mountView()

    expect(view.find('.bubble--user').text()).toBe('Valida o projeto meu-video')
    expect(view.find('.kits').text()).toBe('Kit: Edição e render')
    expect(view.find('details.think').exists()).toBe(true)
    expect(view.find('.step').text()).toContain('validate_project')
    expect(view.find('.ask').text()).toContain('Não confirmada')
    expect(view.findAll('.ask button')).toHaveLength(0)
    expect(view.find('.notice').text()).toContain('o DMaker foi fechado')
    expect(view.find('[data-conversation="c1"]').classes()).toContain('row--active')
  })
})

describe('tela Agente: conversar', () => {
  it('envia o pedido e conta a conversa ao vivo: kit, ferramenta com andamento e resposta', async () => {
    const view = await mountView()
    await sendMessage(view, 'Renderiza o projeto meu-video')

    expect(server.to('POST /api/agent/messages')[0]?.body).toEqual({
      message: 'Renderiza o projeto meu-video',
      mode: 'operate',
      model: 'gpt-oss:20b',
    })
    expect(view.find('.bubble--user').text()).toBe('Renderiza o projeto meu-video')
    expect((view.find('#agent-message').element as HTMLTextAreaElement).value).toBe('')

    emit({ kind: 'triage', t: 1, kits: ['editing'], method: 'keywords' })
    emit({ kind: 'tool_call', t: 2, name: 'render_project', arguments: { name_or_path: 'meu-video', preview: true } })
    emit({ kind: 'tool_progress', t: 3, name: 'render_project', status: 'running', progress: { percent: 40, label: 'encode' } })
    await flushPromises()

    expect(view.find('.kits').text()).toBe('Kit: Edição e render')
    const step = view.find('.step')
    expect(step.text()).toContain('render_project')
    expect(step.text()).toContain('rodando')
    expect(step.text()).toContain('name_or_path=meu-video')
    expect(step.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('40')

    emit({ kind: 'tool_result', t: 4, name: 'render_project', result: '{"status": "done"}' })
    emit({ kind: 'answer', t: 5, text: 'A prévia ficou pronta.' })
    emit(END_DONE)
    await flushPromises()

    expect(view.find('.step').text()).toContain('pronta')
    expect(view.find('.bubble--agent').text()).toBe('A prévia ficou pronta.')
    expect(view.find('.working').exists()).toBe(false)
  })

  it('a linha de status mostra a etapa do servidor com o tempo, no lugar do "Pensando..." fixo', async () => {
    const view = await mountView()
    await sendMessage(view, 'oi')
    expect(view.find('.working').text()).toBe('Aguardando o modelo...')

    emit({ kind: 'status', t: 1, stage: 'loading_model', label: 'Carregando o modelo' })
    await flushPromises()
    expect(view.find('.working').text()).toMatch(/^Carregando o modelo\.\.\. \d+ s$/)
    expect(view.text()).not.toContain('modelo em CPU leva alguns minutos')
  })

  it('a resposta cresce com os trechos e o raciocínio fica recolhido', async () => {
    const view = await mountView()
    await sendMessage(view, 'oi')

    emit({ kind: 'thinking_delta', t: 1, text: 'O usuário cumprimenta.' })
    emit({ kind: 'answer_delta', t: 2, text: 'Olá' })
    await flushPromises()
    expect(view.find('details.think').attributes('open')).toBeUndefined()
    expect(view.find('.bubble--agent').text()).toBe('Olá')
    expect(view.find('.bubble--agent').attributes('data-streaming')).toBe('true')

    emit({ kind: 'answer_delta', t: 3, text: ', tudo bem?' })
    await flushPromises()
    expect(view.find('.bubble--agent').text()).toBe('Olá, tudo bem?')

    emit({ kind: 'answer', t: 4, text: 'Olá, tudo bem?' })
    emit(END_DONE)
    await flushPromises()
    expect(view.find('.bubble--agent').attributes('data-streaming')).toBe('false')
  })

  it('Parar: o botão aparece enquanto responde, diz "Parando" e a resposta parcial fica marcada', async () => {
    const view = await mountView()
    await sendMessage(view, 'Escreve um poema longo')
    emit({ kind: 'answer_delta', t: 1, text: 'O cinema,' })
    await flushPromises()

    expect(view.find('form.composer button[type="submit"]').exists()).toBe(false)
    await buttonNamed(view, 'Parar')!.trigger('click')
    await flushPromises()

    expect(server.to('POST /api/agent/conversations/c1/stop')).toHaveLength(1)
    expect(buttonNamed(view, 'Parando...')!.attributes('disabled')).toBeDefined()
    expect(view.find('.working').text()).toBe('Parando...')

    emit({ kind: 'answer', t: 2, text: 'O cinema,', interrupted: true })
    emit({ kind: 'end', t: 3, status: 'cancelled', error: null, result: { answer: 'O cinema,', interrupted: true } })
    await flushPromises()

    expect(view.find('.bubble--agent').text()).toContain('O cinema,')
    expect(view.find('.bubble--agent').text()).toContain('interrompida')
    expect(view.find('.bubble--error').exists()).toBe(false)
    expect(view.find('.working').exists()).toBe(false)
    expect(buttonNamed(view, 'Enviar')).toBeDefined()
    expect(view.text()).not.toContain('O agente parou sem uma resposta')
  })

  it('a confirmação aparece como botão e o clique segue para o servidor', async () => {
    const view = await mountView()
    await sendMessage(view, 'Renderiza o vídeo final')
    emit({ kind: 'confirmation_request', t: 1, id: 'cf1', tool: 'render_project', question: 'Posso gerar o vídeo final (leva alguns minutos)?', type: 'action' })
    await flushPromises()

    expect(view.text()).toContain('Posso gerar o vídeo final')
    expect(view.find('.working').text()).toBe('Esperando a sua confirmação.')
    const buttons = view.findAll('.ask button')
    expect(buttons.map((button) => button.text())).toEqual(['Confirmar', 'Não fazer'])

    await buttons[0]!.trigger('click')
    await flushPromises()
    expect(server.to('POST /api/agent/confirmations/cf1')[0]?.url).toBe('/api/agent/confirmations/cf1?conversation_id=c1')

    emit({ kind: 'confirmation_answered', t: 2, id: 'cf1', approved: true })
    await flushPromises()
    expect(view.find('.ask').text()).toContain('Você confirmou')
    expect(view.findAll('.ask button')).toHaveLength(0)
  })

  it('clonar voz pergunta, em palavras claras, se o dono autorizou', async () => {
    const view = await mountView()
    await sendMessage(view, 'Clona a voz desta gravação')
    emit({ kind: 'confirmation_request', t: 1, id: 'cf2', tool: 'clone_voice', question: 'Vou clonar a voz joao. A pessoa dona dessa voz autorizou o uso dela?', type: 'voice_consent' })
    await flushPromises()

    expect(view.findAll('.ask button').map((button) => button.text())).toEqual(['O dono da voz autorizou', 'Não autorizou'])
  })

  it('uma chamada barrada aparece como barrada, com o motivo', async () => {
    const view = await mountView()
    await sendMessage(view, 'Faz um reel do vídeo sumido.mp4')
    emit({ kind: 'tool_call', t: 1, name: 'quick_edit', arguments: { src: 'C:/inventado.mp4' } })
    emit({ kind: 'tool_blocked', t: 2, name: 'quick_edit', reason: 'erro: não encontrei C:/inventado.mp4. Pergunte ao usuário.' })
    await flushPromises()

    expect(view.find('.step').text()).toContain('barrada')
    expect(view.find('.step').text()).toContain('Pergunte ao usuário')
  })

  it('um job que falha mostra o erro e libera o campo de mensagem', async () => {
    const view = await mountView()
    await sendMessage(view, 'oi')
    emit({ kind: 'end', t: 1, status: 'error', error: 'TimeoutError: o modelo não respondeu', result: null })
    await flushPromises()

    expect(view.find('.bubble--error').text()).toBe('TimeoutError: o modelo não respondeu')
    expect(view.find('#agent-message').attributes('disabled')).toBeUndefined()
  })

  it('o aviso de aparo da conversa aparece quando o servidor o manda', async () => {
    const view = await mountView()
    await sendMessage(view, 'oi')
    emit({ kind: 'history_trimmed', t: 1, turns: 2, text: 'Tirei os 2 turnos mais antigos para caber no contexto.' })
    await flushPromises()

    expect(view.find('.notice').text()).toContain('Tirei os 2 turnos mais antigos')
  })
})

describe('tela Agente: modo, modelo e esforço', () => {
  it('na conversa nova escolhe o modo, e depois da primeira mensagem ele aparece travado', async () => {
    const view = await mountView()
    await buttonNamed(view, 'Conversa livre')!.trigger('click')
    await flushPromises()

    expect(view.findAll('.example')).toHaveLength(3) // exemplos da conversa livre
    expect(view.find('#agent-message').attributes('placeholder')).toBe('Escreva a sua mensagem')
    expect(view.find('details.kit-list').exists()).toBe(false)

    await sendMessage(view, 'Explica o que é LUFS')
    expect(server.to('POST /api/agent/messages')[0]?.body).toMatchObject({ mode: 'free' })
    expect(view.find('.segmented').exists()).toBe(false)
    expect(view.find('.bar__locked').text()).toContain('Conversa livre')
  })

  it('o modelo e o esforço escolhidos vão com a primeira mensagem', async () => {
    const view = await mountView()
    const [modelSelect, effortSelect] = view.findAll('select')
    expect(modelSelect!.findAll('option').map((option) => option.text())).toEqual(['gpt-oss:20b · 12,8 GB', 'qwen3:30b-a3b · 17,3 GB · não cabe na memória'])

    await effortSelect!.setValue('high')
    await sendMessage(view, 'oi')

    expect(server.to('POST /api/agent/messages')[0]?.body).toEqual({ message: 'oi', mode: 'operate', model: 'gpt-oss:20b', effort: 'high' })
  })

  it('numa conversa salva, trocar o esforço grava no servidor e a mensagem seguinte já usa', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    server = stubAgentServer(
      { 'PATCH /api/agent/conversations/c1': (call: { body: unknown }) => detail({ effort: (call.body as { effort: string | null }).effort }) },
      [detail({ transcript: [{ kind: 'user', id: 'e1', text: 'oi', at: '2026-10-30T12:00:00.000+00:00' }] })],
    )
    const view = await mountView()

    await view.findAll('select')[1]!.setValue('low')
    await flushPromises()
    expect(server.to('PATCH /api/agent/conversations/c1')[0]?.body).toEqual({ effort: 'low' })
    expect((view.findAll('select')[1]!.element as HTMLSelectElement).value).toBe('low')

    await sendMessage(view, 'e agora?')
    expect(server.to('POST /api/agent/messages')[0]?.body).toEqual({ message: 'e agora?', conversation_id: 'c1' })
  })

  it('o modelo que não cabe na memória mostra o aviso e pede confirmação antes de enviar', async () => {
    const view = await mountView()
    await view.findAll('select')[0]!.setValue('qwen3:30b-a3b')
    await flushPromises()
    expect(view.find('.bar__memory').text()).toContain('Não cabe na memória')

    await view.find('#agent-message').setValue('oi')
    await view.find('form.composer').trigger('submit')
    await flushPromises()

    expect(dialog()?.textContent).toContain('qwen3:30b-a3b')
    expect(dialog()?.textContent).toContain('17,3 GB')
    expect(server.to('POST /api/agent/messages')).toHaveLength(0)

    await answerDialog(false)
    expect(server.to('POST /api/agent/messages')).toHaveLength(0)
    expect((view.find('#agent-message').element as HTMLTextAreaElement).value).toBe('oi') // a mensagem não se perde

    await view.find('form.composer').trigger('submit')
    await flushPromises()
    await answerDialog(true)
    expect(server.to('POST /api/agent/messages')[0]?.body).toMatchObject({ model: 'qwen3:30b-a3b' })
  })

  it('memória apertada só avisa e envia direto', async () => {
    server = stubAgentServer({ 'GET /api/agent/models': { ...MODELS, models: [{ ...MODELS.models[0]!, fit: 'tight' }, QWEN] } })
    const view = await mountView()
    expect(view.find('.bar__memory').attributes('data-tone')).toBe('warning')

    await sendMessage(view, 'oi')

    expect(dialog()).toBeNull()
    expect(server.to('POST /api/agent/messages')).toHaveLength(1)
  })
})

describe('tela Agente: modelo sem ferramentas', () => {
  const NO_TOOLS =
    'O modelo gemma3:4b não usa ferramentas. Para operar o DMaker, escolha um modelo com ferramentas; para conversar com ele, use a Conversa livre.'

  it('no modo Operar o modelo aparece avisado e desligado; na Conversa livre dá para escolher e conversar', async () => {
    server = stubAgentServer({ 'GET /api/agent/models': MODELS_WITH_GEMMA })
    const view = await mountView()
    const options = () => view.findAll('select')[0]!.findAll('option')
    const gemma = () => options().find((option) => option.text().startsWith('gemma3:4b'))!

    expect(gemma().text()).toContain('não opera o DMaker')
    expect(gemma().attributes('disabled')).toBeDefined()

    await buttonNamed(view, 'Conversa livre')!.trigger('click')
    await view.findAll('select')[0]!.setValue('gemma3:4b')
    await flushPromises()
    expect(gemma().attributes('disabled')).toBeUndefined()
    expect(view.find('[data-notice="tools"]').exists()).toBe(false)
    expect(view.find('.bar__badges').text()).toContain('Imagem')

    await sendMessage(view, 'Descreve o que é um plano aberto')
    expect(server.to('POST /api/agent/messages')[0]?.body).toEqual({
      message: 'Descreve o que é um plano aberto',
      mode: 'free',
      model: 'gemma3:4b',
    })
  })

  it('voltar para Operar com esse modelo avisa, pede outro modelo e desliga o envio', async () => {
    server = stubAgentServer({ 'GET /api/agent/models': MODELS_WITH_GEMMA })
    const view = await mountView()
    await buttonNamed(view, 'Conversa livre')!.trigger('click')
    await view.findAll('select')[0]!.setValue('gemma3:4b')
    await buttonNamed(view, 'Operar o DMaker')!.trigger('click')
    await flushPromises()

    expect(view.find('[data-notice="tools"]').text()).toBe(NO_TOOLS)
    await view.find('#agent-message').setValue('Corta as pausas deste vídeo')
    expect(view.find('form.composer button[type="submit"]').attributes('disabled')).toBeDefined()
    await view.find('form.composer').trigger('submit')
    await flushPromises()
    expect(server.to('POST /api/agent/messages')).toHaveLength(0)
  })

  it('se o servidor recusar mesmo assim, mostra o detalhe como erro da mensagem e guarda o texto digitado', async () => {
    server = stubAgentServer({ 'POST /api/agent/messages': reply(422, { detail: NO_TOOLS }) })
    const view = await mountView()

    await sendMessage(view, 'Corta as pausas deste vídeo')

    expect(view.find('.failure').text()).toBe(NO_TOOLS)
    expect((view.find('#agent-message').element as HTMLTextAreaElement).value).toBe('Corta as pausas deste vídeo')
    expect(view.find('.bubble--user').exists()).toBe(false)
    expect(buttonNamed(view, 'Enviar')).toBeDefined()
  })
})

describe('tela Agente: lista de conversas', () => {
  const saved = [
    detail({ id: 'c1', title: 'Valida o projeto', transcript: [{ kind: 'user', id: 'e1', text: 'Valida o projeto', at: '2026-10-30T12:00:00.000+00:00' }] }),
    detail({ id: 'c2', title: 'Roteiro do reel', mode: 'free' }),
  ]

  it('lista as conversas salvas e abre a que a pessoa escolhe', async () => {
    server = stubAgentServer(
      {
        'GET /api/agent/conversations/c2': () =>
          detail({ id: 'c2', title: 'Roteiro do reel', mode: 'free', transcript: [{ kind: 'user', id: 'e1', text: 'Me ajuda com o gancho', at: '2026-10-30T12:00:00.000+00:00' }, { kind: 'answer', id: 'e2', text: 'Claro: comece pela dor.', interrupted: false }] }),
      },
      saved,
    )
    const view = await mountView()

    expect(view.findAll('.row').map((row) => row.find('.row__name').text())).toEqual(['Valida o projeto', 'Roteiro do reel'])
    expect(view.find('#agent-message').exists()).toBe(true)

    await view.find('[data-conversation="c2"] .row__open').trigger('click')
    await flushPromises()

    expect(view.find('.bubble--user').text()).toBe('Me ajuda com o gancho')
    expect(view.find('.bubble--agent').text()).toBe('Claro: comece pela dor.')
    expect(view.find('.bar__locked').text()).toContain('Conversa livre')
    expect(localStorage.getItem(OPEN_CONVERSATION_KEY)).toBe('c2')
  })

  it('apagar pede confirmação, e só então vai ao servidor', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    server = stubAgentServer({ 'DELETE /api/agent/conversations/c1': { deleted: 'c1' } }, [saved[0]!])
    const view = await mountView()

    await view.find('button[aria-label="Apagar a conversa Valida o projeto"]').trigger('click')
    await flushPromises()
    expect(dialog()?.textContent).toContain('Apagar esta conversa?')
    expect(dialog()?.textContent).toContain('Valida o projeto')
    expect(server.to('DELETE /api/agent/conversations/c1')).toHaveLength(0)

    await answerDialog(false)
    expect(server.to('DELETE /api/agent/conversations/c1')).toHaveLength(0)
    expect(view.findAll('.row')).toHaveLength(1)

    await view.find('button[aria-label="Apagar a conversa Valida o projeto"]').trigger('click')
    await flushPromises()
    await answerDialog(true)
    expect(server.to('DELETE /api/agent/conversations/c1')).toHaveLength(1)
    expect(view.findAll('.row')).toHaveLength(0)
    expect(view.text()).toContain('O que você quer fazer?')
  })

  it('renomeia a conversa pela lista', async () => {
    server = stubAgentServer(
      { 'PATCH /api/agent/conversations/c1': (call: { body: unknown }) => detail({ title: (call.body as { title: string }).title }) },
      [saved[0]!],
    )
    const view = await mountView()

    await view.find('button[aria-label="Renomear a conversa Valida o projeto"]').trigger('click')
    await view.find('.row__input').setValue('Projeto do casamento')
    await view.find('.row__rename').trigger('submit')
    await flushPromises()

    expect(server.to('PATCH /api/agent/conversations/c1')[0]?.body).toEqual({ title: 'Projeto do casamento' })
    expect(view.find('.row__name').text()).toBe('Projeto do casamento')
  })

  it('"Nova conversa" começa do zero e fica desligado quando já é a conversa nova', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    server = stubAgentServer({}, [saved[0]!])
    const view = await mountView()
    expect(view.find('.bubble--user').exists()).toBe(true)

    const newButton = () => view.findAll('button').find((button) => button.text() === 'Nova conversa')!
    expect(newButton().attributes('disabled')).toBeUndefined()
    await newButton().trigger('click')
    await flushPromises()

    expect(view.find('.bubble--user').exists()).toBe(false)
    expect(view.text()).toContain('O que você quer fazer?')
    expect(newButton().attributes('disabled')).toBeDefined()
    expect(localStorage.getItem(OPEN_CONVERSATION_KEY)).toBeNull()
  })

  it('em tela estreita a lista é uma gaveta que o botão Conversas abre e fecha', async () => {
    const view = await mountView()
    const drawer = view.find('#agent-conversations')
    const toggle = view.find('.agent__toggle')

    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(drawer.classes()).not.toContain('agent__list--open')

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(drawer.classes()).toContain('agent__list--open')
    expect(view.find('.agent__scrim').exists()).toBe(true)

    await view.find('.agent__scrim').trigger('click')
    expect(drawer.classes()).not.toContain('agent__list--open')
  })
})

describe('tela Agente: rota', () => {
  it('o item Agente está na barra lateral e a rota existe', async () => {
    const { NAV_ITEMS } = await import('@/navigation')
    const item = NAV_ITEMS.find((entry) => entry.key === 'agent')

    expect(item).toMatchObject({ label: 'Agente', to: '/agente' })
    const router = createAppRouter(createMemoryHistory())
    expect(router.resolve('/agente').name).toBe('agent')
  })
})

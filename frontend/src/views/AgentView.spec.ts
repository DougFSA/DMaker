import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import type { AgentStatus } from '@/api'
import type { StreamEvent } from '@/lib/agent'
import { createAppRouter } from '@/router'
import AgentView from './AgentView.vue'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  static readonly CLOSED = 2
  readyState = 1
  onmessage: ((message: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null
  constructor(readonly url: string) {
    FakeEventSource.instances.push(this)
  }
  close(): void {
    this.readyState = FakeEventSource.CLOSED
  }
  emit(event: StreamEvent): void {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>)
  }
}

const STATUS: AgentStatus = {
  engine: 'ollama',
  engine_label: 'Ollama',
  model: 'gpt-oss:20b',
  url: 'http://127.0.0.1:11434',
  free_html: false,
  reachable: true,
  model_installed: true,
  kits: [
    { name: 'editing', title: 'Edição e render', description: 'Criar o vídeo e renderizar.', tools: 18 },
    { name: 'voice', title: 'Voz e narração', description: 'Narrar um texto.', tools: 13 },
  ],
}

interface Call {
  method: string
  url: string
  body: unknown
}
let calls: Call[]
let status: AgentStatus

function stubServer(): void {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? 'GET', url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body)))
      if (url === '/api/state') return json({ version: '1', presets: [], brands: [], projects: [] })
      if (url === '/api/agent/status') return json(status)
      if (url === '/api/agent/messages') return json({ job_id: 'j1', conversation_id: 'c1' })
      if (url.startsWith('/api/agent/confirmations/')) return json({ approved: true })
      return Promise.resolve(new Response('{"detail":"nada"}', { status: 404 }))
    }),
  )
}

async function mountView() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agente')
  await router.isReady()
  const wrapper = mount(AgentView, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  status = STATUS
  stubServer()
})
afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

async function sendMessage(wrapper: Awaited<ReturnType<typeof mountView>>, text: string): Promise<FakeEventSource> {
  await wrapper.find('#agent-message').setValue(text)
  await wrapper.find('form.composer').trigger('submit')
  await flushPromises()
  return FakeEventSource.instances[0]!
}

describe('tela Agente', () => {
  it('abre com o modelo configurado, exemplos de pedido e os kits', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('gpt-oss:20b (Ollama)')
    expect(wrapper.text()).toContain('O que você quer fazer?')
    expect(wrapper.findAll('.example')).toHaveLength(4)
    expect(wrapper.find('details.kit-list').text()).toContain('Voz e narração')
  })

  it('clicar num exemplo preenche a mensagem', async () => {
    const wrapper = await mountView()
    await wrapper.find('.example').trigger('click')

    expect((wrapper.find('#agent-message').element as HTMLTextAreaElement).value).toContain('Faz um reel')
  })

  it('mostra o que fazer quando o servidor do modelo está parado e não deixa enviar', async () => {
    status = { ...STATUS, reachable: false, model_installed: false }
    const wrapper = await mountView()

    expect(wrapper.find('[role="alert"]').text()).toContain('O modelo local não está respondendo em http://127.0.0.1:11434')
    await wrapper.find('#agent-message').setValue('oi')
    expect(wrapper.find('form.composer button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  it('avisa que falta o modelo e manda olhar o doctor', async () => {
    status = { ...STATUS, model_installed: false }
    const wrapper = await mountView()

    expect(wrapper.find('[role="alert"]').text()).toContain('dmaker doctor --offline')
  })

  it('envia o pedido e conta a conversa ao vivo: kit, ferramenta com andamento e resposta', async () => {
    const wrapper = await mountView()
    const source = await sendMessage(wrapper, 'Renderiza o projeto meu-video')

    expect(calls.find((call) => call.url === '/api/agent/messages')?.body).toEqual({
      message: 'Renderiza o projeto meu-video',
      conversation_id: null,
    })
    expect(wrapper.find('.bubble--user').text()).toBe('Renderiza o projeto meu-video')
    expect((wrapper.find('#agent-message').element as HTMLTextAreaElement).value).toBe('')

    source.emit({ kind: 'triage', t: 1, kits: ['editing'], method: 'keywords' })
    source.emit({ kind: 'tool_call', t: 2, name: 'render_project', arguments: { name_or_path: 'meu-video', preview: true } })
    source.emit({ kind: 'tool_progress', t: 3, name: 'render_project', status: 'running', progress: { percent: 40, label: 'encode' } })
    await flushPromises()

    expect(wrapper.find('.kits').text()).toBe('Kit: Edição e render')
    const step = wrapper.find('.step')
    expect(step.text()).toContain('render_project')
    expect(step.text()).toContain('rodando')
    expect(step.text()).toContain('name_or_path=meu-video')
    expect(step.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('40')

    source.emit({ kind: 'tool_result', t: 4, name: 'render_project', result: '{"status": "done"}' })
    source.emit({ kind: 'answer', t: 5, text: 'A prévia ficou pronta.' })
    source.emit({ kind: 'end', t: 6, status: 'done', error: null, result: {} })
    await flushPromises()

    expect(wrapper.find('.step').text()).toContain('pronta')
    expect(wrapper.find('.bubble--agent').text()).toBe('A prévia ficou pronta.')
    expect(wrapper.find('.working').exists()).toBe(false)
  })

  it('a confirmação aparece como botão e o clique segue para o servidor', async () => {
    const wrapper = await mountView()
    const source = await sendMessage(wrapper, 'Renderiza o vídeo final')
    source.emit({
      kind: 'confirmation_request',
      t: 1,
      id: 'cf1',
      tool: 'render_project',
      question: 'Posso gerar o vídeo final (leva alguns minutos)?',
      type: 'action',
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Posso gerar o vídeo final')
    expect(wrapper.text()).toContain('Esperando a sua confirmação')
    const buttons = wrapper.findAll('.ask button')
    expect(buttons.map((button) => button.text())).toEqual(['Confirmar', 'Não fazer'])

    await buttons[0]!.trigger('click')
    await flushPromises()
    expect(calls.find((call) => call.url.startsWith('/api/agent/confirmations/'))?.url).toBe(
      '/api/agent/confirmations/cf1?conversation_id=c1',
    )

    source.emit({ kind: 'confirmation_answered', t: 2, id: 'cf1', approved: true })
    await flushPromises()
    expect(wrapper.find('.ask').text()).toContain('Você confirmou')
    expect(wrapper.findAll('.ask button')).toHaveLength(0)
  })

  it('clonar voz pergunta, em palavras claras, se o dono autorizou', async () => {
    const wrapper = await mountView()
    const source = await sendMessage(wrapper, 'Clona a voz desta gravação')
    source.emit({
      kind: 'confirmation_request',
      t: 1,
      id: 'cf2',
      tool: 'clone_voice',
      question: 'Vou clonar a voz joao. A pessoa dona dessa voz autorizou o uso dela?',
      type: 'voice_consent',
    })
    await flushPromises()

    expect(wrapper.findAll('.ask button').map((button) => button.text())).toEqual(['O dono da voz autorizou', 'Não autorizou'])
  })

  it('uma chamada barrada aparece como barrada, com o motivo', async () => {
    const wrapper = await mountView()
    const source = await sendMessage(wrapper, 'Faz um reel do vídeo sumido.mp4')
    source.emit({ kind: 'tool_call', t: 1, name: 'quick_edit', arguments: { src: 'C:/inventado.mp4' } })
    source.emit({ kind: 'tool_blocked', t: 2, name: 'quick_edit', reason: 'erro: não encontrei C:/inventado.mp4. Pergunte ao usuário.' })
    await flushPromises()

    expect(wrapper.find('.step').text()).toContain('barrada')
    expect(wrapper.find('.step').text()).toContain('Pergunte ao usuário')
  })

  it('um job que falha mostra o erro e libera o campo de mensagem', async () => {
    const wrapper = await mountView()
    const source = await sendMessage(wrapper, 'oi')
    source.emit({ kind: 'end', t: 1, status: 'error', error: 'TimeoutError: o modelo não respondeu', result: null })
    await flushPromises()

    expect(wrapper.find('.bubble--error').text()).toBe('TimeoutError: o modelo não respondeu')
    expect(wrapper.find('#agent-message').attributes('disabled')).toBeUndefined()
  })

  it('"Nova conversa" limpa a tela', async () => {
    const wrapper = await mountView()
    const source = await sendMessage(wrapper, 'oi')
    source.emit({ kind: 'end', t: 1, status: 'done', error: null, result: {} })
    await flushPromises()

    const newConversation = wrapper.findAll('button').find((button) => button.text() === 'Nova conversa')!
    await newConversation.trigger('click')
    await flushPromises()

    expect(wrapper.find('.bubble--user').exists()).toBe(false)
    expect(wrapper.text()).toContain('O que você quer fazer?')
  })

  it('o item Agente está na barra lateral e a rota existe', async () => {
    const { NAV_ITEMS } = await import('@/navigation')
    const item = NAV_ITEMS.find((entry) => entry.key === 'agent')

    expect(item).toMatchObject({ label: 'Agente', to: '/agente' })
    const router = createAppRouter(createMemoryHistory())
    expect(router.resolve('/agente').name).toBe('agent')
  })
})

/* A tela Agente com anexos e o painel Avançado (o resto da tela fica em AgentView.spec.ts). */
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
import {
  detail,
  imageAttachment,
  LOADED,
  mediaAttachment,
  MODELS_WITH_GEMMA,
  removes,
  stubConversationServer,
  textAttachment,
  uploads,
  type AgentServer,
} from '@/test/agentServer'
import { FakeEventSource } from '@/test/fetch'
import { reply } from '@/test/routedFetch'
import AgentView from './AgentView.vue'

let server: AgentServer
let wrapper: VueWrapper | null = null

async function mountView(): Promise<VueWrapper> {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agente')
  await router.isReady()
  const Host = defineComponent({ render: () => [h(AgentView), h(ConfirmHost)] })
  wrapper = mount(Host, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

function stub(extra: Record<string, unknown> = {}, conversations = [] as ReturnType<typeof detail>[]): void {
  server = stubConversationServer({ 'GET /api/state': { version: '1', presets: [], brands: [], projects: [] }, ...extra }, conversations)
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  stub()
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const END_DONE: StreamEvent = { kind: 'end', t: 9, status: 'done', error: null, result: {} }
const file = (name: string, type = '') => new File(['x'], name, { type })
const buttonNamed = (view: VueWrapper, label: string) => view.findAll('button').find((button) => button.text() === label)
const dialog = () => document.body.querySelector('[role="alertdialog"]')

/** Escolhe arquivos como a pessoa faria no seletor do botão Anexar. */
async function pick(view: VueWrapper, ...files: File[]): Promise<void> {
  const input = view.find('.composer input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  await input.trigger('change')
  await flushPromises()
}

async function answerDialog(accepted: boolean): Promise<void> {
  useConfirmStore().answer(accepted)
  await flushPromises()
}

describe('tela Agente: anexos', () => {
  it('o botão Anexar fica na caixa de mensagem e aceita os tipos que o servidor conhece', () => {
    return mountView().then((view) => {
      const input = view.find('.composer input[type="file"]')
      expect(buttonNamed(view, 'Anexar')).toBeDefined()
      expect(input.attributes('multiple')).toBeDefined()
      expect(input.attributes('accept')).toContain('.pdf')
      expect(input.attributes('accept')).toContain('.mp4')
      expect(view.find('.composer__above').exists()).toBe(false)
    })
  })

  it('anexar no rascunho cria a conversa e mostra a ficha do arquivo com o tamanho e o aviso de corte', async () => {
    stub({
      'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment({ size: 20480, chars: 12400, total_chars: 38000, truncated: true })),
    })
    const view = await mountView()

    await pick(view, file('roteiro.docx'))

    expect(server.to('POST /api/agent/conversations')).toHaveLength(1)
    const card = view.find('.composer__above .file')
    expect(card.find('.file__name').text()).toBe('roteiro.docx')
    expect(card.find('.file__meta').text()).toBe('Documento · 20 KB')
    expect(card.find('.file__note').text()).toBe('cortado: 12.400 de 38.000 caracteres')
    expect(localStorage.getItem(OPEN_CONVERSATION_KEY)).toBe('c1')
  })

  it('a imagem mostra a miniatura servida pela conversa, e não por /api/file', async () => {
    stub({ 'GET /api/agent/models': MODELS_WITH_GEMMA, 'POST /api/agent/conversations/c1/attachments': uploads(() => imageAttachment()) })
    const view = await mountView()
    await buttonNamed(view, 'Conversa livre')!.trigger('click')
    await view.findAll('select')[0]!.setValue('gemma3:4b')
    await flushPromises()

    await pick(view, file('foto.png', 'image/png'))

    const thumb = view.find('.composer__above img')
    expect(thumb.attributes('src')).toBe('/api/agent/conversations/c1/attachments/a2')
  })

  it('colar uma imagem anexa o arquivo', async () => {
    stub({ 'GET /api/agent/models': MODELS_WITH_GEMMA, 'POST /api/agent/conversations/c1/attachments': uploads(() => imageAttachment({ name: 'image.png' })) })
    const view = await mountView()
    await buttonNamed(view, 'Conversa livre')!.trigger('click')
    await view.findAll('select')[0]!.setValue('gemma3:4b')
    await flushPromises()
    const print = file('image.png', 'image/png')
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: { files: [print] } })

    view.find('#agent-message').element.dispatchEvent(event)
    await flushPromises()

    expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(1)
    expect(view.find('.composer__above .file__name').text()).toBe('image.png')
  })

  it('soltar arquivos na caixa anexa uma vez só, mesmo caindo sobre o botão Anexar', async () => {
    stub({ 'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()) })
    const view = await mountView()

    await view.find('.composer .upload__zone').trigger('drop', { dataTransfer: { files: [file('roteiro.docx')], types: ['Files'] } })
    await flushPromises()
    expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(1)

    await view.find('.composer').trigger('drop', { dataTransfer: { files: [file('outro.txt')], types: ['Files'] } })
    await flushPromises()
    expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(2)
  })

  it('com um anexo e o campo vazio, Enviar liga e a mensagem é "Veja o anexo." com o id do anexo', async () => {
    stub({ 'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()) })
    const view = await mountView()
    const send = () => view.find('form.composer button[type="submit"]')
    expect(send().attributes('disabled')).toBeDefined()

    await pick(view, file('roteiro.docx'))
    expect(send().attributes('disabled')).toBeUndefined()
    await view.find('form.composer').trigger('submit')
    await flushPromises()

    expect(server.to('POST /api/agent/messages')[0]?.body).toEqual({ message: 'Veja o anexo.', conversation_id: 'c1', attachments: ['a1'] })
    expect(view.find('.bubble--user').text()).toBe('Veja o anexo.')
    expect(view.find('.sent__files .file__name').text()).toBe('roteiro.docx')
    expect(view.find('.composer__above').exists()).toBe(false)
  })

  it('o vídeo anexado no modo Operar vai com o texto digitado', async () => {
    stub({ 'POST /api/agent/conversations/c1/attachments': uploads(() => mediaAttachment()) })
    const view = await mountView()

    await pick(view, file('aula.mp4', 'video/mp4'))
    await view.find('#agent-message').setValue('Corta as pausas deste vídeo')
    await view.find('form.composer').trigger('submit')
    await flushPromises()

    expect(server.to('POST /api/agent/messages')[0]?.body).toEqual({
      message: 'Corta as pausas deste vídeo',
      conversation_id: 'c1',
      attachments: ['a3'],
    })
    expect(view.find('.sent__files .file__meta').text()).toBe('Vídeo · 4 MB')
  })

  it('tirar a ficha chama o servidor e a ficha some', async () => {
    stub({
      'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()),
      'DELETE /api/agent/conversations/c1/attachments/a1': removes('a1'),
    })
    const view = await mountView()
    await pick(view, file('roteiro.docx'))

    await view.find('button[aria-label="Remover roteiro.docx"]').trigger('click')
    await flushPromises()

    expect(server.to('DELETE /api/agent/conversations/c1/attachments/a1')).toHaveLength(1)
    expect(view.find('.composer__above').exists()).toBe(false)
  })

  it('o arquivo que o servidor recusa mostra o motivo na ficha, sem perder o texto digitado', async () => {
    stub({ 'POST /api/agent/conversations/c1/attachments': uploads(() => reply(422, { detail: 'contrato.pdf: o PDF está protegido por senha.' })) })
    const view = await mountView()
    await view.find('#agent-message').setValue('olha isso')

    await pick(view, file('contrato.pdf'))

    expect(view.find('.composer__above .file__error').text()).toBe('contrato.pdf: o PDF está protegido por senha.')
    expect((view.find('#agent-message').element as HTMLTextAreaElement).value).toBe('olha isso')
  })

  it('um tipo que o servidor não conhece é recusado na escolha, com a lista legível dos aceitos, sem subir', async () => {
    const view = await mountView()

    await pick(view, file('programa.exe'))

    const problem = view.find('.composer .upload__problem').text()
    expect(problem).toContain('Não aceitei programa.exe')
    expect(problem).toContain('imagem (PNG, JPG, WebP), vídeo, áudio, planilha (CSV, XLSX) e texto')
    expect(server.to('POST /api/agent/conversations')).toHaveLength(0)
  })

  it('recusa na tela o que passa de 8 anexos', async () => {
    let next = 0
    stub({ 'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment({ id: `a${(next += 1)}`, name: `f${next}.txt` })) })
    const view = await mountView()

    await pick(view, ...Array.from({ length: 9 }, (_, index) => file(`f${index}.txt`)))

    expect(view.findAll('.composer__above .file')).toHaveLength(8)
    expect(view.find('[data-code="notice"]').text()).toContain('no máximo 8 anexos')
    expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(8)
  })

  it('vídeo numa Conversa livre é recusado na escolha, com o aviso do modo Operar', async () => {
    const view = await mountView()
    await buttonNamed(view, 'Conversa livre')!.trigger('click')

    await pick(view, file('aula.mp4', 'video/mp4'))

    expect(server.to('POST /api/agent/conversations')).toHaveLength(0)
    expect(view.find('[data-code="notice"]').text()).toContain('modo Operar o DMaker')
  })

  it('a conversa salva volta com os anexos pendentes como fichas', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    stub({}, [detail({ messages: 0, mode_locked: false, pending_attachments: [textAttachment(), imageAttachment()] })])
    const view = await mountView()

    expect(view.findAll('.composer__above .file__name').map((name) => name.text())).toEqual(['roteiro.docx', 'foto.png'])
  })
})

describe('tela Agente: aviso de imagem antes de enviar', () => {
  async function withImage(models = MODELS_WITH_GEMMA): Promise<VueWrapper> {
    stub({ 'GET /api/agent/models': models, 'POST /api/agent/conversations/c1/attachments': uploads(() => imageAttachment()) })
    const view = await mountView()
    await buttonNamed(view, 'Conversa livre')!.trigger('click')
    await pick(view, file('foto.png', 'image/png'))
    return view
  }

  it('o gpt-oss não lê imagem: o aviso aparece antes de enviar, sugere o gemma3 e segura o envio', async () => {
    const view = await withImage()
    await view.find('#agent-message').setValue('descreve a imagem')

    const warning = view.find('[data-code="image_without_vision"]')
    expect(warning.text()).toContain('O modelo gpt-oss:20b não lê imagem')
    expect(warning.text()).toContain('gemma3:4b')
    expect(view.find('form.composer button[type="submit"]').attributes('disabled')).toBeDefined()
    await view.find('form.composer').trigger('submit')
    await flushPromises()
    expect(server.to('POST /api/agent/messages')).toHaveLength(0)
  })

  it('o botão do aviso troca para o modelo que lê imagem, e o aviso some', async () => {
    const view = await withImage()

    await view.find('[data-code="image_without_vision"] button').trigger('click')
    await flushPromises()

    expect(view.find('[data-code="image_without_vision"]').exists()).toBe(false)
    expect((view.findAll('select')[0]!.element as HTMLSelectElement).value).toBe('gemma3:4b')
    await view.find('#agent-message').setValue('descreve a imagem')
    expect(view.find('form.composer button[type="submit"]').attributes('disabled')).toBeUndefined()
  })

  it('no modo Operar, diz que nenhum modelo instalado lê imagem e opera o DMaker e aponta a Conversa livre', async () => {
    stub({ 'GET /api/agent/models': MODELS_WITH_GEMMA, 'POST /api/agent/conversations/c1/attachments': uploads(() => imageAttachment()) })
    const view = await mountView()

    await pick(view, file('foto.png', 'image/png'))

    const text = view.find('[data-code="image_without_vision"]').text()
    expect(text).toContain('nenhum modelo instalado lê imagem e opera o DMaker')
    expect(text).toContain('abra uma Conversa livre')
    expect(view.find('[data-code="image_without_vision"] button').exists()).toBe(false)
  })

  it('se o servidor ainda recusar (422), mostra o motivo, oferece os modelos sugeridos e guarda o texto e a ficha', async () => {
    const message = 'O modelo gpt-oss:20b não aceita imagens. Escolha um destes: gemma3:4b.'
    stub({
      // capacidades desconhecidas: a tela não avisa antes, e o servidor recusa
      'GET /api/agent/models': { ...MODELS_WITH_GEMMA, models: [{ ...MODELS_WITH_GEMMA.models[0]!, capabilities: [] }, MODELS_WITH_GEMMA.models[1]!] },
      'POST /api/agent/conversations/c1/attachments': uploads(() => imageAttachment()),
      'POST /api/agent/messages': reply(422, { detail: message, error: message, suggested_models: ['gemma3:4b'] }),
    })
    const view = await mountView()
    await buttonNamed(view, 'Conversa livre')!.trigger('click')
    await pick(view, file('foto.png', 'image/png'))
    await view.find('#agent-message').setValue('descreve a imagem')

    await view.find('form.composer').trigger('submit')
    await flushPromises()

    expect(view.find('.failure').text()).toContain(message)
    expect(view.find('.failure button').text()).toBe('Usar gemma3:4b')
    expect((view.find('#agent-message').element as HTMLTextAreaElement).value).toBe('descreve a imagem')
    expect(view.find('.composer__above .file__name').text()).toBe('foto.png')
  })
})

describe('tela Agente: avançado', () => {
  it('fica recolhido, com o contexto, a temperatura e a semente, e o aviso de que trocar o contexto recarrega o modelo', async () => {
    const view = await mountView()
    const panel = view.find('details.advanced')

    expect(panel.exists()).toBe(true)
    expect(panel.attributes('open')).toBeUndefined()
    expect(panel.findAll('label').map((label) => label.text())).toEqual(['Contexto (tokens)', 'Temperatura', 'Semente'])
    expect(panel.find('[data-notice="context"]').text()).toContain('alguns minutos')
  })

  it('o contexto escolhido vai com a primeira mensagem, e o limite é o contexto do modelo', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      const view = await mountView()
      const context = view.find('details.advanced input[type="number"]')
      expect(context.attributes('max')).toBe('131072')

      await context.setValue('8192')
      vi.advanceTimersByTime(700)
      await view.find('#agent-message').setValue('oi')
      await view.find('form.composer').trigger('submit')
      await flushPromises()

      expect(server.to('POST /api/agent/messages')[0]?.body).toMatchObject({ options: { num_ctx: 8192 } })
    } finally {
      vi.useRealTimers()
    }
  })

  it('abrir o painel lê o que está carregado e mostra a memória que o modelo usa', async () => {
    stub({ 'GET /api/agent/loaded': LOADED })
    const view = await mountView()
    const details = view.find('details.advanced')
    ;(details.element as HTMLDetailsElement).open = true
    await details.trigger('toggle')
    await flushPromises()

    expect(view.find('.advanced__loaded').text()).toContain('gpt-oss:20b · 9,4 GB na memória · contexto 16.384')
  })

  it('Descarregar chama o servidor e o modelo sai da lista', async () => {
    let loaded = LOADED
    stub({
      'GET /api/agent/loaded': () => loaded,
      'POST /api/agent/unload': () => {
        loaded = { ...LOADED, models: [] }
        return { model: 'gpt-oss:20b', unloaded: true }
      },
    })
    const view = await mountView()
    const details = view.find('details.advanced')
    ;(details.element as HTMLDetailsElement).open = true
    await details.trigger('toggle')
    await flushPromises()

    await view.find('.advanced__loaded button').trigger('click')
    await flushPromises()

    expect(server.to('POST /api/agent/unload')[0]?.body).toEqual({ model: 'gpt-oss:20b' })
    expect(view.find('.advanced__loaded').text()).toContain('Nenhum modelo está carregado')
    expect(dialog()).toBeNull() // sem resposta em andamento, não pergunta nada
  })

  it('descarregar durante uma resposta pede confirmação, e o 409 do servidor aparece como motivo', async () => {
    stub({
      'GET /api/agent/loaded': LOADED,
      'POST /api/agent/unload': reply(409, { detail: 'Pare a resposta do agente antes de descarregar o modelo.' }),
    })
    const view = await mountView()
    await view.find('#agent-message').setValue('oi')
    await view.find('form.composer').trigger('submit')
    await flushPromises()
    const details = view.find('details.advanced')
    ;(details.element as HTMLDetailsElement).open = true
    await details.trigger('toggle')
    await flushPromises()

    await view.find('.advanced__loaded button').trigger('click')
    await flushPromises()
    expect(dialog()?.textContent).toContain('Descarregar o modelo durante uma resposta?')
    expect(server.to('POST /api/agent/unload')).toHaveLength(0)

    await answerDialog(true)
    expect(server.to('POST /api/agent/unload')).toHaveLength(1)
    expect(view.find('.advanced__error').text()).toBe('Pare a resposta do agente antes de descarregar o modelo.')
    FakeEventSource.latest().emit(END_DONE)
  })

  it('no motor compatível com a OpenAI o painel só tem temperatura e semente', async () => {
    stub({ 'GET /api/agent/models': { ...MODELS_WITH_GEMMA, engine: 'openai' } })
    const view = await mountView()

    expect(view.find('details.advanced').findAll('label').map((label) => label.text())).toEqual(['Temperatura', 'Semente'])
    expect(view.find('.advanced__loaded').exists()).toBe(false)
  })
})

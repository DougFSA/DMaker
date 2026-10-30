import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentOptions } from '@/api'
import { GPT_OSS, LOADED } from '@/test/agentServer'
import AgentAdvanced from './AgentAdvanced.vue'

type Props = InstanceType<typeof AgentAdvanced>['$props']

let wrapper: VueWrapper | null = null

function mountAdvanced(props: Partial<Props> = {}): VueWrapper {
  wrapper = mount(AgentAdvanced, {
    props: {
      engine: 'ollama',
      model: GPT_OSS,
      options: {} as AgentOptions,
      disabled: false,
      loaded: LOADED.models,
      unloading: null,
      unloadError: '',
      ...props,
    },
  })
  return wrapper
}

const inputs = (view: VueWrapper) => view.findAll('input[type="number"]')

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.useRealTimers()
})

describe('AgentAdvanced', () => {
  it('nasce recolhido, com o contexto, a temperatura e a semente', () => {
    const view = mountAdvanced()

    expect(view.find('details').attributes('open')).toBeUndefined()
    expect(view.find('summary').text()).toBe('Avançado')
    expect(view.findAll('label').map((label) => label.text())).toEqual(['Contexto (tokens)', 'Temperatura', 'Semente'])
  })

  it('o contexto vai até o máximo do modelo e avisa que mais contexto pede mais memória e recarrega o modelo', () => {
    const view = mountAdvanced()
    const context = inputs(view)[0]!

    expect(context.attributes('max')).toBe('131072')
    expect(context.attributes('min')).toBe('512')
    expect(view.text()).toContain('De 512 até 131.072 tokens')
    const warning = view.find('[data-notice="context"]').text()
    expect(warning).toContain('mais memória')
    expect(warning).toContain('recarregar')
    expect(warning).toContain('alguns minutos')
  })

  it('mostra as opções que a conversa já tem', () => {
    const view = mountAdvanced({ options: { num_ctx: 8192, temperature: 0.4, seed: 7 } })

    expect(inputs(view).map((input) => (input.element as HTMLInputElement).value)).toEqual(['8192', '0.4', '7'])
  })

  it('grava um instante depois da última tecla, só com o que tem valor', async () => {
    const view = mountAdvanced()
    await inputs(view)[0]!.setValue('8192')
    await inputs(view)[2]!.setValue('42')

    expect(view.emitted('update:options')).toBeUndefined()
    vi.advanceTimersByTime(700)
    expect(view.emitted('update:options')).toEqual([[{ num_ctx: 8192, seed: 42 }]])
  })

  it('esvaziar o campo volta ao padrão', async () => {
    const view = mountAdvanced({ options: { temperature: 0.4 } })
    await inputs(view)[1]!.setValue('')
    vi.advanceTimersByTime(700)

    expect(view.emitted('update:options')).toEqual([[{}]])
  })

  it('valor fora do limite mostra o motivo e não é gravado', async () => {
    const view = mountAdvanced()
    await inputs(view)[0]!.setValue('200000')
    await inputs(view)[1]!.setValue('3')
    vi.advanceTimersByTime(700)

    const alerts = view.findAll('[role="alert"]').map((alert) => alert.text())
    expect(alerts).toContain('Este modelo vai até 131.072 tokens.')
    expect(alerts).toContain('A temperatura vai de 0 a 2.')
    expect(view.emitted('update:options')).toBeUndefined()
  })

  it('o valor igual ao que já vale não manda gravar de novo', async () => {
    const view = mountAdvanced({ options: { num_ctx: 8192 } })
    await inputs(view)[0]!.setValue('8192')
    vi.advanceTimersByTime(700)

    expect(view.emitted('update:options')).toBeUndefined()
  })

  it('enquanto o agente responde, os campos ficam parados e a dica diz por quê', () => {
    const view = mountAdvanced({ disabled: true })

    expect(inputs(view).every((input) => input.attributes('disabled') !== undefined)).toBe(true)
    expect(view.text()).toContain('Espere a resposta terminar para mudar.')
  })

  it('mostra o modelo carregado com a memória que ele usa, e Descarregar pede para descarregá-lo', async () => {
    const view = mountAdvanced()

    expect(view.find('.advanced__loaded').text()).toContain('gpt-oss:20b · 9,4 GB na memória · contexto 16.384')
    await view.find('.advanced__loaded button').trigger('click')
    expect(view.emitted('unload')).toEqual([['gpt-oss:20b']])
  })

  it('sem modelo carregado, diz que não há nenhum; enquanto lê, diz que está lendo', () => {
    expect(mountAdvanced({ loaded: [] }).find('.advanced__loaded').text()).toContain('Nenhum modelo está carregado')
    expect(mountAdvanced({ loaded: null }).find('.advanced__loaded').text()).toContain('Lendo o que está na memória')
  })

  it('enquanto descarrega, o botão fica ocupado; a recusa do servidor aparece embaixo', () => {
    const view = mountAdvanced({ unloading: 'gpt-oss:20b', unloadError: 'Pare a resposta do agente antes de descarregar o modelo.' })

    expect(view.find('.advanced__loaded button').attributes('disabled')).toBeDefined()
    expect(view.find('.advanced__error').text()).toBe('Pare a resposta do agente antes de descarregar o modelo.')
  })

  it('no motor compatível com a OpenAI esconde o contexto, o que está carregado e o descarregar', () => {
    const view = mountAdvanced({ engine: 'openai', loaded: null })

    expect(view.findAll('label').map((label) => label.text())).toEqual(['Temperatura', 'Semente'])
    expect(view.find('.advanced__loaded').exists()).toBe(false)
    expect(view.find('[data-notice="context"]').exists()).toBe(false)
  })

  it('cada vez que o painel abre, pede a leitura do que está carregado; fechar não pede nada', async () => {
    const view = mountAdvanced()
    const details = view.find('details').element as HTMLDetailsElement

    details.open = true
    await view.find('details').trigger('toggle')
    expect(view.emitted('open')).toHaveLength(1)
    details.open = false
    await view.find('details').trigger('toggle')
    expect(view.emitted('open')).toHaveLength(1)
    details.open = true
    await view.find('details').trigger('toggle')
    expect(view.emitted('open')).toHaveLength(2)
  })

  it('as opções que mudam por fora (outra conversa aberta) aparecem nos campos', async () => {
    const view = mountAdvanced({ options: { seed: 1 } })
    await view.setProps({ options: { seed: 99, num_ctx: 4096 } })

    expect(inputs(view).map((input) => (input.element as HTMLInputElement).value)).toEqual(['4096', '', '99'])
  })
})

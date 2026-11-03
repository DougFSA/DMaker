import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { AgentModel } from '@/api'
import AgentChatBar from './AgentChatBar.vue'

const GIB = 1024 ** 3

function model(overrides: Partial<AgentModel> = {}): AgentModel {
  return {
    name: 'gpt-oss:20b',
    size: Math.round(12.8 * GIB),
    family: 'gptoss',
    capabilities: ['tools', 'thinking'],
    context_length: 131072,
    effort_levels: [
      { value: 'low', label: 'Baixo' },
      { value: 'medium', label: 'Médio' },
      { value: 'high', label: 'Alto' },
    ],
    default_effort: 'medium',
    fit: 'fits',
    loaded: false,
    ...overrides,
  }
}

const QWEN = model({
  name: 'qwen3:30b-a3b',
  size: Math.round(17.3 * GIB),
  effort_levels: [
    { value: 'off', label: 'Desligado' },
    { value: 'on', label: 'Ligado' },
  ],
  default_effort: 'on',
  fit: 'too_big',
})

describe('AgentChatBar', () => {
  const baseProps = {
    mode: 'operate' as const,
    modeLocked: false,
    models: [model(), QWEN],
    memory: { total: Math.round(15.7 * GIB), available: 2 * GIB },
    modelName: 'gpt-oss:20b',
    selected: model(),
    effort: null,
    busy: false,
  }

  it('na conversa nova o modo é um seletor de dois botões; clicar troca o modo', async () => {
    const wrapper = mount(AgentChatBar, { props: baseProps })
    const buttons = wrapper.findAll('.segmented button')

    expect(buttons.map((button) => button.text())).toEqual(['Operar o DMaker', 'Conversa livre'])
    await buttons[1]!.trigger('click')
    expect(wrapper.emitted('update:mode')).toEqual([['free']])
  })

  it('depois da primeira mensagem o modo aparece travado, sem seletor', () => {
    const wrapper = mount(AgentChatBar, { props: { ...baseProps, modeLocked: true, mode: 'free' } })

    expect(wrapper.find('.segmented').exists()).toBe(false)
    expect(wrapper.find('.bar__locked').text()).toContain('Conversa livre')
    expect(wrapper.find('.bar__locked').text()).toContain('não muda depois da primeira mensagem')
  })

  it('o seletor de modelo mostra o tamanho e o que não cabe, e a escolha sobe para a tela', async () => {
    const wrapper = mount(AgentChatBar, { props: baseProps })
    const select = wrapper.findAll('select')[0]!

    expect(select.findAll('option').map((option) => option.text())).toEqual([
      'gpt-oss:20b · 12,8 GB',
      'qwen3:30b-a3b · 17,3 GB · não cabe na memória',
    ])
    await select.setValue('qwen3:30b-a3b')
    expect(wrapper.emitted('update:model')).toEqual([['qwen3:30b-a3b']])
  })

  it('o seletor de esforço usa os níveis do modelo e a opção vazia diz o padrão', async () => {
    const wrapper = mount(AgentChatBar, { props: { ...baseProps, effort: 'high' } })
    const effort = wrapper.findAll('select')[1]!

    expect(effort.findAll('option').map((option) => option.text())).toEqual(['Padrão do modelo (Médio)', 'Baixo', 'Médio', 'Alto'])
    expect(effort.element.value).toBe('high')

    await effort.setValue('low')
    await effort.setValue('')
    expect(wrapper.emitted('update:effort')).toEqual([['low'], [null]])
  })

  it('sem níveis de esforço (motor openai ou modelo sem raciocínio), o seletor some', () => {
    const wrapper = mount(AgentChatBar, {
      props: { ...baseProps, selected: model({ effort_levels: [], capabilities: ['tools'] }) },
    })

    expect(wrapper.findAll('select')).toHaveLength(1)
  })

  it('mostra os selos do que o modelo faz', () => {
    const wrapper = mount(AgentChatBar, { props: { ...baseProps, selected: model({ capabilities: ['vision', 'tools', 'thinking'] }) } })
    expect(wrapper.findAll('.bar__badges li').map((item) => item.text())).toEqual(['Imagem', 'Ferramentas', 'Raciocínio'])
  })

  it('avisa quando a memória está apertada e quando o modelo não cabe', () => {
    const tight = mount(AgentChatBar, { props: { ...baseProps, selected: model({ fit: 'tight' }) } })
    expect(tight.find('.bar__memory').attributes('data-tone')).toBe('warning')

    const big = mount(AgentChatBar, { props: { ...baseProps, modelName: 'qwen3:30b-a3b', selected: QWEN } })
    expect(big.find('.bar__memory').attributes('data-tone')).toBe('error')
    expect(big.find('.bar__memory').text()).toContain('Não cabe na memória')

    expect(mount(AgentChatBar, { props: baseProps }).find('.bar__memory').exists()).toBe(false)
  })

  it('respondendo, o modelo fica travado até o fim da resposta', () => {
    const wrapper = mount(AgentChatBar, { props: { ...baseProps, busy: true } })
    expect(wrapper.findAll('select')[0]!.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('O modelo só muda entre uma resposta e outra')
  })

  it('sem a lista de modelos, mostra só o modelo da conversa', () => {
    const wrapper = mount(AgentChatBar, { props: { ...baseProps, models: [], selected: undefined } })
    expect(wrapper.findAll('select')[0]!.findAll('option').map((option) => option.text())).toEqual(['gpt-oss:20b'])
  })

  it('o modelo da conversa que já não está instalado continua na lista, avisado', () => {
    const wrapper = mount(AgentChatBar, { props: { ...baseProps, modelName: 'llama3:8b', selected: undefined } })
    expect(wrapper.findAll('select')[0]!.findAll('option')[0]!.text()).toBe('llama3:8b · não instalado')
  })

  describe('modelo sem ferramentas', () => {
    const gemma = model({ name: 'gemma3:4b', size: Math.round(3.1 * GIB), capabilities: ['vision'], effort_levels: [], default_effort: null })

    it('no modo Operar aparece avisado e não se escolhe', () => {
      const wrapper = mount(AgentChatBar, { props: { ...baseProps, models: [model(), gemma, QWEN] } })
      const option = wrapper.findAll('select')[0]!.findAll('option').find((item) => item.text().startsWith('gemma3:4b'))!

      expect(option.text()).toBe('gemma3:4b · 3,1 GB · não opera o DMaker')
      expect(option.attributes('disabled')).toBeDefined()
      expect(wrapper.find('[data-notice="tools"]').exists()).toBe(false)
    })

    it('na Conversa livre é escolhível normalmente', () => {
      const wrapper = mount(AgentChatBar, { props: { ...baseProps, mode: 'free', models: [model(), gemma, QWEN] } })
      const option = wrapper.findAll('select')[0]!.findAll('option').find((item) => item.text().startsWith('gemma3:4b'))!

      expect(option.text()).toBe('gemma3:4b · 3,1 GB')
      expect(option.attributes('disabled')).toBeUndefined()
    })

    it('se o modelo atual não tem ferramentas e a conversa opera o DMaker, avisa e pede outro modelo', () => {
      const wrapper = mount(AgentChatBar, {
        props: { ...baseProps, models: [model(), gemma], modelName: 'gemma3:4b', selected: gemma },
      })
      const notice = wrapper.find('[data-notice="tools"]')

      expect(notice.text()).toContain('O modelo gemma3:4b não usa ferramentas')
      expect(notice.text()).toContain('escolha um modelo com ferramentas')
      expect(notice.text()).toContain('use a Conversa livre')
      expect(notice.attributes('role')).toBe('alert')
    })

    it('mostra o selo de imagem e, sem raciocínio, não mostra o seletor de esforço', () => {
      const wrapper = mount(AgentChatBar, {
        props: { ...baseProps, mode: 'free', models: [model(), gemma], modelName: 'gemma3:4b', selected: gemma },
      })

      expect(wrapper.findAll('.bar__badges li').map((item) => item.text())).toEqual(['Imagem'])
      expect(wrapper.findAll('select')).toHaveLength(1)
      expect(wrapper.find('[data-notice="tools"]').exists()).toBe(false)
    })

    it('o motor que não informa capacidades não bloqueia nenhum modelo', () => {
      const unknown = model({ name: 'qwen2.5-7b', capabilities: [], effort_levels: [], default_effort: null, size: null })
      const wrapper = mount(AgentChatBar, { props: { ...baseProps, models: [unknown], modelName: 'qwen2.5-7b', selected: unknown } })

      expect(wrapper.findAll('select')[0]!.findAll('option')[0]!.attributes('disabled')).toBeUndefined()
      expect(wrapper.find('[data-notice="tools"]').exists()).toBe(false)
    })
  })

  it('tem um lugar para as opções avançadas da entrega seguinte', () => {
    const wrapper = mount(AgentChatBar, { props: baseProps, slots: { advanced: '<details class="adv">Avançado</details>' } })
    expect(wrapper.find('.adv').exists()).toBe(true)
  })
})

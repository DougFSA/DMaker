import { describe, expect, it } from 'vitest'
import { DRAGONFLY_LV2, ECHO_LV2, STEPS_LADSPA } from '@/test/audioPluginsFixtures'
import {
  clampControl,
  controlAsParam,
  controlValue,
  isPluginChoice,
  newPluginEffect,
  pluginAsEffectInfo,
  pluginEffectFromChoice,
  pluginOf,
  pluginProblem,
  usablePlugins,
} from './audioPlugins'

describe('achar o plugin de um efeito da spec', () => {
  const all = [ECHO_LV2, STEPS_LADSPA, DRAGONFLY_LV2]

  it('casa o formato e a referência', () => {
    expect(pluginOf(all, { format: 'lv2', plugin: 'urn:dmaker:test:echo' })).toBe(ECHO_LV2)
    expect(pluginOf(all, { format: 'ladspa', plugin: 'passos.dll#passos' })).toBe(STEPS_LADSPA)
  })

  it('a mesma referência em outro formato, ou uma que não existe, não casa', () => {
    expect(pluginOf(all, { format: 'ladspa', plugin: 'urn:dmaker:test:echo' })).toBeUndefined()
    expect(pluginOf(all, { format: 'lv2', plugin: 'urn:acme:nada' })).toBeUndefined()
  })

  it('o menu só oferece o que o ffmpeg hospeda e a pessoa não desligou', () => {
    expect(usablePlugins([ECHO_LV2, { ...STEPS_LADSPA, enabled: false }, DRAGONFLY_LV2])).toEqual([ECHO_LV2])
  })
})

describe('o efeito novo e os valores dos controles', () => {
  it('nasce só com o formato e a referência: os controles ficam no padrão do plugin', () => {
    expect(newPluginEffect(ECHO_LV2)).toEqual({ type: 'plugin', format: 'lv2', plugin: 'urn:dmaker:test:echo' })
  })

  it('o valor é o da spec ou o padrão do plugin', () => {
    const control = ECHO_LV2.controls[0]!
    expect(controlValue({ params: { delay_ms: 300 } }, control)).toBe(300)
    expect(controlValue({ params: {} }, control)).toBe(250)
    expect(controlValue({}, control)).toBe(250)
    expect(controlValue({ params: { delay_ms: 'x' } }, control)).toBe(250)
  })

  it('limita à faixa que o plugin declara, e ao inteiro nos controles inteiros', () => {
    expect(clampControl(ECHO_LV2.controls[0]!, 5000)).toBe(1000)
    expect(clampControl(ECHO_LV2.controls[0]!, -3)).toBe(1)
    expect(clampControl(STEPS_LADSPA.controls[0]!, 3.6)).toBe(4)
    expect(clampControl({ kind: 'number', minimum: null, maximum: null }, 123.4)).toBe(123.4)
  })
})

describe('por que um plugin não vai tocar', () => {
  it('diz o motivo, e fica vazio quando toca', () => {
    expect(pluginProblem(ECHO_LV2)).toBe('')
    expect(pluginProblem(undefined)).toContain('não está instalado')
    expect(pluginProblem({ ...ECHO_LV2, enabled: false })).toContain('desabilitado')
    expect(pluginProblem(DRAGONFLY_LV2)).toContain('Options feature missing')
  })
})

describe('o plugin como um efeito do catálogo, para a janela do painel Áudio', () => {
  it('vira um efeito com um parâmetro por controle, com faixa e padrão', () => {
    const info = pluginAsEffectInfo(ECHO_LV2)
    expect(info.type).toBe('plugin:lv2-f6c94886b1')
    expect(info.label).toBe('Plugin: DMaker Eco (LV2)')
    expect(info.parameters.map((parameter) => [parameter.name, parameter.default, parameter.minimum, parameter.maximum])).toEqual([
      ['delay_ms', 250, 1, 1000],
      ['feedback', 0.4, 0, 0.95],
      ['mix', 0.5, 0, 1],
    ])
    expect(isPluginChoice(info.type)).toBe(true)
    expect(isPluginChoice('normalize')).toBe(false)
  })

  it('o controle liga/desliga do LADSPA vira uma caixa de marcar', () => {
    expect(controlAsParam(STEPS_LADSPA.controls[1]!)).toMatchObject({ kind: 'boolean', default: true })
    expect(controlAsParam(STEPS_LADSPA.controls[0]!)).toMatchObject({ kind: 'integer', default: 4 })
  })

  it('o que a janela aplica é o efeito Plugin da spec, com os valores como número', () => {
    expect(pluginEffectFromChoice(STEPS_LADSPA, { c0: 6, c1: false, ignorado: 'texto' })).toEqual({
      type: 'plugin',
      format: 'ladspa',
      plugin: 'passos.dll#passos',
      params: { c0: 6, c1: 0 },
    })
  })
})

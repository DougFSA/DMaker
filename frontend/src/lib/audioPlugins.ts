/* Contas puras dos plugins de efeito (LV2 e LADSPA) para a interface: achar o plugin que um efeito da spec cita, montar o
   efeito novo e descrever um plugin como um efeito do catálogo (para a janela do painel Áudio montar o formulário dele
   do mesmo jeito que monta o de qualquer outro). Nada aqui conhece um plugin pelo nome. */
import type { AudioEffectInfo, AudioEffectParam, AudioEffectSettings, PluginControl, PluginInfo } from '@/api'

/** O `type` do efeito Plugin na spec. */
export const PLUGIN_TYPE = 'plugin'

/** O prefixo dos "efeitos" que a janela do painel oferece, um por plugin: `plugin:lv2-1a2b3c4d5e`. */
export const PLUGIN_CHOICE_PREFIX = 'plugin:'

/** O plugin que um efeito Plugin da spec cita, ou undefined (não instalado, ou a varredura ainda não o conhece). */
export function pluginOf(plugins: readonly PluginInfo[], effect: Pick<AudioEffectSettings, 'format' | 'plugin'>): PluginInfo | undefined {
  return plugins.find((candidate) => candidate.format === effect.format && candidate.ref === effect.plugin)
}

/** Os plugins que o menu oferece: os que o ffmpeg hospeda e a pessoa não desligou. */
export function usablePlugins(plugins: readonly PluginInfo[]): PluginInfo[] {
  return plugins.filter((plugin) => plugin.usable && plugin.enabled)
}

/** O efeito novo para um plugin: os valores dos controles ficam de fora, o plugin usa o padrão dele até a pessoa mexer. */
export function newPluginEffect(plugin: Pick<PluginInfo, 'format' | 'ref'>): AudioEffectSettings {
  return { type: PLUGIN_TYPE, format: plugin.format, plugin: plugin.ref }
}

/** Por que o efeito Plugin da spec não vai tocar aqui, ou vazio quando vai. */
export function pluginProblem(plugin: PluginInfo | undefined): string {
  if (!plugin) return 'Este plugin não está instalado nesta máquina: o efeito é pulado no render. Instale-o e varra de novo.'
  if (!plugin.usable) return `Este plugin não pode ser usado: ${plugin.problem}`
  if (!plugin.enabled) return 'Este plugin está desabilitado: o efeito é pulado no render.'
  return ''
}

/** O valor de um controle: o que a spec guarda, ou o padrão do plugin. */
export function controlValue(effect: Record<string, unknown>, control: Pick<PluginControl, 'name' | 'default'>): number {
  const params = effect.params
  const stored = typeof params === 'object' && params !== null ? (params as Record<string, unknown>)[control.name] : undefined
  return typeof stored === 'number' ? stored : control.default
}

/** Limita o número à faixa que o plugin declara (e ao inteiro, nos controles inteiros). */
export function clampControl(control: Pick<PluginControl, 'kind' | 'minimum' | 'maximum'>, value: number): number {
  let result = control.kind === 'integer' ? Math.round(value) : value
  if (typeof control.minimum === 'number' && result < control.minimum) result = control.minimum
  if (typeof control.maximum === 'number' && result > control.maximum) result = control.maximum
  return result
}

/** Um controle do plugin como parâmetro de catálogo, para o formulário genérico da janela do painel. */
export function controlAsParam(control: PluginControl): AudioEffectParam {
  return {
    name: control.name,
    label: control.label,
    kind: control.kind,
    unit: '',
    default: control.kind === 'boolean' ? control.default !== 0 : control.default,
    minimum: control.minimum,
    maximum: control.maximum,
    hint: control.kind === 'boolean' ? '' : `Controle ${control.name} do plugin.`,
    options: [],
  }
}

/** O plugin descrito como um efeito do catálogo: a janela do painel Áudio o põe na lista de efeitos e monta o formulário a partir dos controles. */
export function pluginAsEffectInfo(plugin: PluginInfo): AudioEffectInfo {
  return {
    type: `${PLUGIN_CHOICE_PREFIX}${plugin.id}`,
    label: `Plugin: ${plugin.name} (${plugin.format.toUpperCase()})`,
    audacity_name: plugin.format === 'lv2' ? 'Plugin LV2' : 'Plugin LADSPA',
    summary: `Plugin ${plugin.format.toUpperCase()}${plugin.maker ? ` de ${plugin.maker}` : ''}. Os controles vêm do próprio plugin.`,
    changes_duration: false,
    parameters: plugin.controls.map(controlAsParam),
  }
}

/** Se o "efeito" escolhido na janela é um plugin (e não um efeito do catálogo). */
export function isPluginChoice(type: string): boolean {
  return type.startsWith(PLUGIN_CHOICE_PREFIX)
}

/** O efeito Plugin da spec que a janela do painel grava: o plugin escolhido, com os valores dos controles que a pessoa deu. */
export function pluginEffectFromChoice(
  plugin: Pick<PluginInfo, 'format' | 'ref'>,
  values: Record<string, unknown>,
): { type: string; format: string; plugin: string; params: Record<string, number> } {
  const params: Record<string, number> = {}
  for (const [name, value] of Object.entries(values)) {
    if (typeof value === 'number') params[name] = value
    else if (typeof value === 'boolean') params[name] = value ? 1 : 0
  }
  return { type: PLUGIN_TYPE, format: plugin.format, plugin: plugin.ref, params }
}

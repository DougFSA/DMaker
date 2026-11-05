/* Os plugins de mentira dos testes: o mesmo formato do `GET /api/audio-plugins` (PluginService.catalog), com um LV2 mono que
   funciona, um LADSPA com controle inteiro e liga/desliga, e um LV2 que o ffmpeg não consegue hospedar. */
import type { AudioEffectInfo, PluginCatalog, PluginInfo } from '@/api'

/** O efeito Plugin como o catálogo de efeitos o descreve (`audio_effects`): os três campos, sem controle de plugin nenhum. */
export const PLUGIN_EFFECT_INFO: AudioEffectInfo = {
  type: 'plugin',
  label: 'Plugin',
  audacity_name: 'Plugins LV2 e LADSPA',
  summary: 'Aplica um plugin de efeito de terceiros (LV2 ou LADSPA) instalado nesta máquina.',
  changes_duration: false,
  needs_selection: true,
  sample_stage: true,
  parameters: [
    { name: 'format', label: 'Formato', kind: 'plugin_format', unit: '', default: 'lv2', minimum: null, maximum: null, hint: '', options: [] },
    { name: 'plugin', label: 'Plugin', kind: 'plugin', unit: '', default: '', minimum: null, maximum: null, hint: '', options: [] },
    { name: 'params', label: 'Controles', kind: 'plugin_params', unit: '', default: null, minimum: null, maximum: null, hint: '', options: [] },
  ],
}

export const ECHO_LV2: PluginInfo = {
  id: 'lv2-f6c94886b1',
  format: 'lv2',
  ref: 'urn:dmaker:test:echo',
  name: 'DMaker Eco',
  path: 'C:/plugins/echo.lv2',
  binary: 'C:/plugins/echo.lv2/echo.dll',
  maker: 'DMaker',
  usable: true,
  problem: '',
  enabled: true,
  ports: { inputs: 1, outputs: 1 },
  controls: [
    { name: 'delay_ms', label: 'Atraso', default: 250, minimum: 1, maximum: 1000, kind: 'number' },
    { name: 'feedback', label: 'Realimentação', default: 0.4, minimum: 0, maximum: 0.95, kind: 'number' },
    { name: 'mix', label: 'Mistura', default: 0.5, minimum: 0, maximum: 1, kind: 'number' },
  ],
}

export const STEPS_LADSPA: PluginInfo = {
  id: 'ladspa-5136d1b9ff',
  format: 'ladspa',
  ref: 'passos.dll#passos',
  name: 'Passos',
  path: 'C:/plugins/passos.dll',
  binary: 'C:/plugins/passos.dll',
  maker: '',
  usable: true,
  problem: '',
  enabled: true,
  ports: { inputs: 1, outputs: 1 },
  controls: [
    { name: 'c0', label: 'Passos', default: 4, minimum: 1, maximum: 8, kind: 'integer' },
    { name: 'c1', label: 'Ligado', default: 1, minimum: 0, maximum: 1, kind: 'boolean' },
  ],
}

export const DRAGONFLY_LV2: PluginInfo = {
  id: 'lv2-951a5baf07',
  format: 'lv2',
  ref: 'https://github.com/michaelwillis/dragonfly-reverb',
  name: 'DragonflyHallReverb',
  path: 'C:/plugins/DragonflyHallReverb.lv2',
  binary: 'C:/plugins/DragonflyHallReverb.lv2/DragonflyHallReverb_dsp.dll',
  maker: '',
  usable: false,
  problem: 'Options feature missing, cannot continue! (o plugin exige options, schedule, que o ffmpeg não oferece ao hospedar LV2)',
  enabled: true,
  ports: { inputs: 2, outputs: 2 },
  controls: [],
}

export function audioPluginCatalog(plugins: PluginInfo[] = [ECHO_LV2, STEPS_LADSPA, DRAGONFLY_LV2]): PluginCatalog {
  return {
    plugins,
    notes: [],
    hosts: { lv2: 'C:/ff/ffmpeg-lv2.exe', ladspa: 'C:/ff/ffmpeg.exe' },
    folders: [{ format: 'lv2', path: 'C:/dados/plugins', exists: false }],
    install_to: 'C:/dados/plugins',
  }
}

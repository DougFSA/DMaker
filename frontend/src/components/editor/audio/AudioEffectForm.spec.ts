import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { AudioEffectInfo, AudioEffectParam } from '@/api'
import AudioEffectForm from './AudioEffectForm.vue'

function param(extra: Partial<AudioEffectParam> & Pick<AudioEffectParam, 'name' | 'label' | 'kind'>): AudioEffectParam {
  return { unit: '', default: null, minimum: null, maximum: null, hint: '', options: [], ...extra }
}

const info: AudioEffectInfo = {
  type: 'change_tempo',
  label: 'Mudar Andamento',
  audacity_name: 'Change Tempo',
  summary: '',
  changes_duration: true,
  parameters: [
    param({ name: 'mode', label: 'Unidade', kind: 'choice', default: 'percent', options: ['percent', 'bpm'] }),
    param({ name: 'percent', label: 'Mudança', kind: 'number', default: 0, shown_when: { mode: 'percent' } }),
    param({ name: 'bpm_from', label: 'BPM de origem', kind: 'number', default: 120, shown_when: { mode: 'bpm' } }),
    param({ name: 'bpm_to', label: 'BPM de destino', kind: 'number', default: 128, shown_when: { mode: 'bpm' } }),
  ],
}

const fieldNames = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('[data-effect-param]').map((element) => element.attributes('data-effect-param'))

describe('AudioEffectForm: unidades', () => {
  it('mostra só os campos do modo escolhido e troca quando o modo muda', async () => {
    const wrapper = mount(AudioEffectForm, { props: { info, modelValue: { mode: 'percent', percent: 0 } } })
    expect(fieldNames(wrapper)).toEqual(['mode', 'percent'])
    await wrapper.setProps({ modelValue: { mode: 'bpm', percent: 0 } })
    expect(fieldNames(wrapper)).toEqual(['mode', 'bpm_from', 'bpm_to'])
  })

  it('sem o modo no rascunho vale o padrão do catálogo', () => {
    const wrapper = mount(AudioEffectForm, { props: { info, modelValue: {} } })
    expect(fieldNames(wrapper)).toEqual(['mode', 'percent'])
  })
})

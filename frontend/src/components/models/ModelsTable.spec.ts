import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { JobRunView } from '@/components/speech/JobRunStatus.vue'
import { DEFAULT_MODELS } from '@/test/modelsServer'
import ModelsTable from './ModelsTable.vue'

function running(over: Partial<JobRunView> = {}): JobRunView {
  return { running: true, label: 'Na fila...', percent: null, startedAtMs: Date.now(), cancelling: false, error: '', cancelled: false, ...over }
}

function table(props: { downloads?: Record<string, JobRunView>; busy?: (id: string) => boolean } = {}) {
  return mount(ModelsTable, {
    props: { models: DEFAULT_MODELS, downloads: props.downloads ?? {}, busy: props.busy ?? (() => false) },
  })
}

const rowOf = (wrapper: ReturnType<typeof table>, id: string) => wrapper.find(`[data-model="${id}"]`)

describe('ModelsTable', () => {
  it('tem as colunas modelo, estado, no disco e licença', () => {
    const headers = table().findAll('th').map((cell) => cell.text())
    expect(headers).toEqual(['Modelo', 'Estado', 'No disco', 'Licença'])
  })

  it('o botão de cada linha diz a qual modelo se refere', () => {
    const wrapper = table()
    expect(rowOf(wrapper, 'omnivoice').find('button').attributes('aria-label')).toBe('Apagar OmniVoice')
    expect(rowOf(wrapper, 'audioseal').find('button').attributes('aria-label')).toBe("Baixar (89,1 MB): AudioSeal (marca d'água)")
  })

  it('emite o modelo da linha ao baixar e ao apagar', async () => {
    const wrapper = table()
    await rowOf(wrapper, 'audioseal').find('button').trigger('click')
    await rowOf(wrapper, 'omnivoice').find('button').trigger('click')
    expect(wrapper.emitted('download')![0]).toEqual([DEFAULT_MODELS[2]])
    expect(wrapper.emitted('remove')![0]).toEqual([DEFAULT_MODELS[0]])
  })

  it('trava só os botões do modelo ocupado', () => {
    const wrapper = table({ busy: (id) => id === 'demucs-htdemucs' })
    const disabled = (id: string) => rowOf(wrapper, id).findAll('button').map((button) => button.attributes('disabled') !== undefined)
    expect(disabled('demucs-htdemucs')).toEqual([true, true])
    expect(disabled('omnivoice')).toEqual([false])
  })

  it('mostra o andamento do download na linha do modelo', () => {
    const wrapper = table({ downloads: { audioseal: running({ label: 'AudioSeal: 10 MB de 89 MB', percent: 11 }) } })
    expect(rowOf(wrapper, 'audioseal').text()).toContain('AudioSeal: 10 MB de 89 MB')
    expect(rowOf(wrapper, 'audioseal').find('[role="progressbar"]').attributes('aria-valuenow')).toBe('11')
    expect(rowOf(wrapper, 'omnivoice').find('[role="progressbar"]').exists()).toBe(false)
  })
})

import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import EditorInspector from './EditorInspector.vue'
// os painéis carregam sob demanda; já importados, o teste não espera a compilação deles
import './CaptionsPanel.vue'
import './JsonPanel.vue'
import './PreviewPanel.vue'
import './PropertiesPanel.vue'

afterEach(() => vi.unstubAllGlobals())

const tabLabels = (wrapper: Awaited<ReturnType<typeof mountEditorPart>>) =>
  wrapper.findAll('[role="tab"]').map((tab) => tab.text())

async function pick(wrapper: Awaited<ReturnType<typeof mountEditorPart>>, label: string): Promise<void> {
  const tab = wrapper.findAll('[role="tab"]').find((candidate) => candidate.text() === label)
  // o Reka UI troca de aba no mousedown com o botão principal
  await tab?.trigger('mousedown', { button: 0, ctrlKey: false })
  await flushPromises()
}

/** Monta o inspetor com a aba ativa controlada pelo pai, como a tela do editor faz. */
async function mountInspector(opened: Awaited<ReturnType<typeof openEditor>>, start = 'properties') {
  const active = ref(start)
  const Host = defineComponent({
    setup: () => () =>
      h(EditorInspector, { modelValue: active.value, 'onUpdate:modelValue': (value: string) => (active.value = value) }),
  })
  const wrapper = await mountEditorPart(Host, opened)
  return { wrapper, active }
}

describe('EditorInspector', () => {
  it('mostra as abas Propriedades, JSON e Preview; Legendas só com legendas automáticas', async () => {
    const opened = await openEditor()
    const { wrapper } = await mountInspector(opened)
    expect(tabLabels(wrapper)).toEqual(['Propriedades', 'JSON', 'Preview'])
    opened.store.captionsExists = true
    await flushPromises()
    expect(tabLabels(wrapper)).toEqual(['Propriedades', 'JSON', 'Legendas', 'Preview'])
  })

  it('a aba ativa mostra o painel dela', async () => {
    const opened = await openEditor()
    const { wrapper } = await mountInspector(opened, 'json')
    await flushPromises()
    expect(wrapper.find('textarea').exists()).toBe(true)
    expect(wrapper.find('.properties').exists()).toBe(false)
  })

  it('trocar de aba muda o painel e avisa o pai', async () => {
    const opened = await openEditor()
    const { wrapper, active } = await mountInspector(opened)
    await flushPromises()
    expect(wrapper.find('.properties').exists()).toBe(true)
    await pick(wrapper, 'JSON')
    expect(active.value).toBe('json')
    expect(wrapper.find('textarea').exists()).toBe(true)
  })

  it('a aba já aberta continua montada, escondida: o texto do JSON digitado não se perde', async () => {
    const opened = await openEditor()
    const { wrapper } = await mountInspector(opened, 'json')
    await flushPromises()
    await wrapper.find('textarea').setValue('{ "rascunho": true }')
    await pick(wrapper, 'Propriedades')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('{ "rascunho": true }')
    expect(wrapper.find('textarea').element.closest('[data-state="inactive"]')).not.toBeNull()
    await pick(wrapper, 'JSON')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('{ "rascunho": true }')
  })

  it('a aba que ainda não foi aberta não carrega nada (o preview não pede o QA nem a catalog à toa)', async () => {
    const opened = await openEditor()
    const { fetch } = opened
    const { wrapper } = await mountInspector(opened)
    await flushPromises()
    expect(wrapper.find('.preview').exists()).toBe(false)
    expect(wrapper.find('.captions').exists()).toBe(false)
    expect(fetch.to('GET /api/projects/demo/captions')).toHaveLength(0)
  })

  it('a aba lembrada que este projeto não tem (Legendas, sem legendas automáticas) abre em Propriedades', async () => {
    const opened = await openEditor()
    const { wrapper, active } = await mountInspector(opened, 'captions')
    await flushPromises()
    expect(active.value).toBe('properties')
    expect(wrapper.find('[role="tab"][data-state="active"]').text()).toBe('Propriedades')
    expect(wrapper.find('.properties').exists()).toBe(true)
  })

  it('se a aba ativa some (as legendas acabaram), volta para Propriedades', async () => {
    const opened = await openEditor()
    opened.store.captionsExists = true
    const { wrapper, active } = await mountInspector(opened, 'captions')
    await flushPromises()
    opened.store.captionsExists = false
    await flushPromises()
    expect(active.value).toBe('properties')
    expect(wrapper.find('[role="tab"][data-state="active"]').text()).toBe('Propriedades')
  })
})

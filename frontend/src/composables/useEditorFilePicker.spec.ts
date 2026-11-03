import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import { provideEditorFilePicker, useEditorFilePicker, type EditorFilePicker, type PickFile } from './useEditorFilePicker'

/** Monta um pai que provê o seletor e um filho que o usa, como a tela do editor e os campos de arquivo. */
function mountPicker() {
  let host!: EditorFilePicker
  let pick!: PickFile | null
  const Child = defineComponent({
    setup() {
      pick = useEditorFilePicker()
      return () => h('span')
    },
  })
  const Host = defineComponent({
    setup() {
      host = provideEditorFilePicker()
      return () => h(Child)
    },
  })
  mount(Host)
  return { host, pick: pick as PickFile }
}

describe('seletor de arquivos do editor', () => {
  it('fora da tela do editor não há seletor', () => {
    let pick: PickFile | null = undefined as unknown as PickFile | null
    mount(
      defineComponent({
        setup() {
          pick = useEditorFilePicker()
          return () => h('span')
        },
      }),
    )
    expect(pick).toBeNull()
  })

  it('pedir um arquivo abre o diálogo e escolher devolve o caminho', async () => {
    const { host, pick } = mountPicker()
    expect(host.open.value).toBe(false)
    const chosen = pick()
    expect(host.open.value).toBe(true)
    host.onSelect(['C:/midia/a.mp4'])
    await expect(chosen).resolves.toBe('C:/midia/a.mp4')
  })

  it('fechar o diálogo sem escolher dá null', async () => {
    const { host, pick } = mountPicker()
    const chosen = pick()
    await flushPromises() // o diálogo chega a abrir na tela
    host.open.value = false // Cancelar, Esc ou clique fora
    await flushPromises()
    await expect(chosen).resolves.toBeNull()
  })

  it('escolher e depois o diálogo fechar não responde duas vezes', async () => {
    const { host, pick } = mountPicker()
    const chosen = pick()
    await flushPromises()
    host.onSelect(['C:/midia/a.mp4'])
    host.open.value = false
    await flushPromises()
    await expect(chosen).resolves.toBe('C:/midia/a.mp4')
  })

  it('um segundo pedido cancela o primeiro, que ainda estava aberto', async () => {
    const { host, pick } = mountPicker()
    const first = pick()
    const second = pick()
    await expect(first).resolves.toBeNull()
    host.onSelect(['C:/midia/b.mp4'])
    await expect(second).resolves.toBe('C:/midia/b.mp4')
  })
})

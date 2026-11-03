import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { projectDetail, projectSpec } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import { reply } from '@/test/routedFetch'
import DiskChangeBanner from './DiskChangeBanner.vue'

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
})

const button = (label: string) => wrapper!.findAll('button').find((candidate) => candidate.text() === label)

describe('DiskChangeBanner', () => {
  it('não aparece enquanto o disco e a edição andam juntos', async () => {
    const opened = await openEditor()
    wrapper = await mountEditorPart(DiskChangeBanner, opened)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('com mudança não salva, diz o que cada ação faz', async () => {
    const opened = await openEditor(projectSpec(), { 'PUT /api/projects/demo': reply(409, { detail: 'mudou', revision: 'rev-2' }) })
    wrapper = await mountEditorPart(DiskChangeBanner, opened)
    opened.store.setField('output.quality', 'draft')
    await opened.store.save()
    await flushPromises()
    const alert = wrapper.find('[role="alert"]')
    expect(alert.text()).toContain('O projeto mudou fora do editor (pelo Claude, pelo agente ou pela CLI)')
    expect(alert.text()).toContain('descarta as suas')
    expect(alert.text()).toContain('grava por cima')
    expect(button('Recarregar do disco')).toBeDefined()
    expect(button('Manter o meu')).toBeDefined()
  })

  it('as duas ações ficam paradas enquanto o Salvar está em andamento', async () => {
    let release: (value: unknown) => void = () => undefined
    const opened = await openEditor(projectSpec(), { 'PUT /api/projects/demo': reply(409, { detail: 'mudou', revision: 'rev-2' }) })
    wrapper = await mountEditorPart(DiskChangeBanner, opened)
    opened.store.setField('output.quality', 'draft')
    await opened.store.save()
    opened.fetch.set('PUT /api/projects/demo', () => new Promise((resolve) => (release = resolve)))
    const keeping = opened.store.keepMine()
    await flushPromises()
    expect(button('Recarregar do disco')?.attributes('disabled')).toBeDefined()
    release({ ok: true, spec_path: 'x', revision: 'rev-3' })
    await keeping
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('"Recarregar do disco" traz a spec do disco e fecha a faixa', async () => {
    const onDisk = { ...projectSpec(), name: 'demo', output: { ...(projectSpec().output as object), quality: 'max' } }
    const opened = await openEditor(projectSpec(), { 'PUT /api/projects/demo': reply(409, { detail: 'mudou', revision: 'rev-2' }) })
    wrapper = await mountEditorPart(DiskChangeBanner, opened)
    opened.store.setField('output.quality', 'draft')
    await opened.store.save()
    opened.fetch.set('GET /api/projects/demo', () => projectDetail({ spec: onDisk as never, revision: 'rev-2' }))
    await button('Recarregar do disco')?.trigger('click')
    await flushPromises()
    expect(opened.store.get('output.quality')).toBe('max')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})

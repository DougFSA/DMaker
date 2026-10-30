import { effectScope, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installFakeMatchMedia } from '@/test/mediaQuery'
import { NARROW_QUERY, useMediaQuery } from './useMediaQuery'

afterEach(() => vi.unstubAllGlobals())

describe('useMediaQuery', () => {
  it('lê o valor na hora, sem esperar a primeira mudança', () => {
    installFakeMatchMedia(true)
    const scope = effectScope()
    const matches = scope.run(() => useMediaQuery(NARROW_QUERY))
    expect(matches?.value).toBe(true)
    scope.stop()
  })

  it('acompanha a janela quando ela cruza o limite', async () => {
    const media = installFakeMatchMedia(false)
    const scope = effectScope()
    const matches = scope.run(() => useMediaQuery(NARROW_QUERY))
    expect(matches?.value).toBe(false)

    media.set(true)
    await nextTick()
    expect(matches?.value).toBe(true)

    media.set(false)
    await nextTick()
    expect(matches?.value).toBe(false)
    scope.stop()
  })

  it('para de ouvir quando o escopo termina', () => {
    const media = installFakeMatchMedia(false)
    const scope = effectScope()
    scope.run(() => useMediaQuery(NARROW_QUERY))
    expect(media.listenerCount()).toBe(1)
    scope.stop()
    expect(media.listenerCount()).toBe(0)
  })

  it('sem matchMedia no ambiente, vale falso', () => {
    vi.stubGlobal('matchMedia', undefined)
    const scope = effectScope()
    const matches = scope.run(() => useMediaQuery(NARROW_QUERY))
    expect(matches?.value).toBe(false)
    scope.stop()
  })
})

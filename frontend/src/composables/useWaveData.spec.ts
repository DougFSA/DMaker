import { describe, expect, it } from 'vitest'
import { columnsFor } from './useWaveData'

describe('quantas colunas pedir', () => {
  it('uma por pixel do dispositivo, dentro do que a rota aceita', () => {
    expect(columnsFor(1000, 1)).toBe(1000)
    expect(columnsFor(1000, 2)).toBe(2000)
    expect(columnsFor(3000, 2)).toBe(4096)
    expect(columnsFor(10, 1)).toBe(64)
    expect(columnsFor(800, 0.5)).toBe(800) // tela com zoom do navegador abaixo de 100%
  })

  it('sem largura medida ainda, pede um tamanho razoável', () => {
    expect(columnsFor(0, 1)).toBe(512)
    expect(columnsFor(Number.NaN, 1)).toBe(512)
  })
})

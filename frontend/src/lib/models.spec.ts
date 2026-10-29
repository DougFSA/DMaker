import { describe, expect, it } from 'vitest'
import type { ModelInventory, ModelLeftover, ModelStatus } from '@/api'
import {
  canDownload,
  canRemove,
  downloadLabel,
  leftoverLine,
  leftoversTotal,
  listPreview,
  pruneWarning,
  sizeCell,
  stateLabel,
  stateTone,
  summaryParts,
  usedByText,
} from './models'

function model(over: Partial<ModelStatus> = {}): ModelStatus {
  return {
    id: 'omnivoice',
    name: 'OmniVoice',
    purpose: 'Fala em mais de 600 idiomas.',
    engine: 'omnivoice',
    license: 'Apache-2.0',
    required_by: ['Narração', 'Dublagem'],
    state: 'installed',
    size_bytes: 3_267_869_931,
    size_label: '3,04 GB',
    expected_bytes: 3_267_869_931,
    expected_label: '3,04 GB',
    ...over,
  }
}

const LEFTOVER: ModelLeftover = { path: 'velho/modelo.bin', size_bytes: 2_097_152, size_label: '2,0 MB', is_dir: false }
const LEFTOVER_DIR: ModelLeftover = { path: 'restos', size_bytes: 1_048_576, size_label: '1,0 MB', is_dir: true }

function inventory(over: Partial<ModelInventory> = {}): ModelInventory {
  return {
    models_dir: 'X:/dados/cache/models',
    models: [model()],
    leftovers: [],
    total_bytes: 4_000_000_000,
    total_label: '3,73 GB',
    leftover_bytes: 0,
    leftover_label: '0 B',
    disk_free_bytes: 50_000_000_000,
    disk_free_label: '46,57 GB',
    ...over,
  }
}

describe('estado do modelo', () => {
  it('diz baixado, incompleto e não baixado, com a cor de cada um', () => {
    expect(stateLabel('installed')).toBe('baixado')
    expect(stateLabel('partial')).toBe('incompleto')
    expect(stateLabel('absent')).toBe('não baixado')
    expect(stateTone('installed')).toBe('success')
    expect(stateTone('partial')).toBe('warning')
    expect(stateTone('absent')).toBe('neutral')
  })
})

describe('coluna "No disco"', () => {
  it('modelo baixado mostra só o tamanho medido', () => {
    expect(sizeCell(model())).toEqual({ size: '3,04 GB', note: '' })
  })

  it('download pela metade mostra o que já tem e de quanto é', () => {
    expect(sizeCell(model({ state: 'partial', size_label: '1,2 GB' }))).toEqual({ size: '1,2 GB', note: 'de ~3,04 GB' })
  })

  it('modelo que não foi baixado diz quanto vai ocupar', () => {
    expect(sizeCell(model({ state: 'absent', size_label: '0 B' }))).toEqual({ size: '', note: 'ocupa ~3,04 GB ao baixar' })
  })
})

describe('ações', () => {
  it('baixar vale para o que não está inteiro, apagar para o que tem algo em disco', () => {
    expect([canDownload(model()), canRemove(model())]).toEqual([false, true])
    expect([canDownload(model({ state: 'partial' })), canRemove(model({ state: 'partial' }))]).toEqual([true, true])
    expect([canDownload(model({ state: 'absent' })), canRemove(model({ state: 'absent' }))]).toEqual([true, false])
  })

  it('o botão de baixar diz o tamanho, e o de um download pela metade diz continuar', () => {
    expect(downloadLabel(model({ state: 'absent' }))).toBe('Baixar (3,04 GB)')
    expect(downloadLabel(model({ state: 'partial' }))).toBe('Continuar download')
  })
})

describe('textos', () => {
  it('lista as funções que dependem do modelo, ou nada se nenhuma depende', () => {
    expect(usedByText(model())).toBe('Usado por: Narração; Dublagem')
    expect(usedByText(model({ required_by: [] }))).toBe('')
  })

  it('o resumo do disco mostra as sobras só quando elas existem', () => {
    expect(summaryParts(inventory())).toEqual(['Ocupado em cache/models: 3,73 GB', 'Livre no disco: 46,57 GB'])
    const withLeftovers = inventory({ leftovers: [LEFTOVER], leftover_label: '2,0 MB' })
    expect(summaryParts(withLeftovers)).toEqual([
      'Ocupado em cache/models: 3,73 GB',
      'Livre no disco: 46,57 GB',
      'Sobras: 2,0 MB',
    ])
  })

  it('o resumo some com o disco livre quando o servidor não consegue medir', () => {
    expect(summaryParts(inventory({ disk_free_bytes: null, disk_free_label: null }))).toEqual([
      'Ocupado em cache/models: 3,73 GB',
    ])
  })

  it('a sobra que é pasta ganha a barra no fim', () => {
    expect(leftoverLine(LEFTOVER)).toBe('velho/modelo.bin: 2,0 MB')
    expect(leftoverLine(LEFTOVER_DIR)).toBe('restos/: 1,0 MB')
  })

  it('o total e o aviso contam os itens e o espaço', () => {
    const both = inventory({ leftovers: [LEFTOVER, LEFTOVER_DIR], leftover_label: '3,0 MB' })
    expect(leftoversTotal(both)).toBe('2 item(ns), 3,0 MB')
    expect(pruneWarning(both)).toBe(
      'Vai apagar 2 item(ns) que nenhum modelo do DMaker usa e liberar 3,0 MB. Confira a lista: se algum é de um modelo seu, cancele.',
    )
  })

  it('a lista do diálogo vai numa linha só, e o que passa do limite vira "e mais N"', () => {
    expect(listPreview(['omnivoice', 'kokoro/voices-v1.0.bin'])).toBe('omnivoice · kokoro/voices-v1.0.bin')
    expect(listPreview(['a', 'b', 'c', 'd'], 2)).toBe('a · b · e mais 2')
    expect(listPreview([])).toBe('')
  })
})

/* O catálogo do painel Filtros: quais grupos de campos valem para cada tipo de item (clipe, imagem, cartão, PiP, texto,
   imagem sobreposta, barra, faixa, música, legendas e o projeto). É só dado, em `filterCatalog.json`: um grupo novo
   ou um tipo novo de item entra como uma linha no JSON, sem formulário escrito à mão. Opções, limites e padrões de
   cada campo vêm do schema da spec (`editorSchema.ts`); aqui ficam o rótulo, o passo das setas e o que é opcional.
   O JSON é conferido contra o schema de verdade em `tests/test_filter_catalog_contract.py`. */
import type { FieldDef, FieldKind } from './editorFields'
import catalogData from './filterCatalog.json'

export type FilterTarget =
  | 'clip'
  | 'image'
  | 'card'
  | 'video'
  | 'text'
  | 'image-overlay'
  | 'progress-bar'
  | 'track'
  | 'music'
  | 'captions'
  | 'project'

/** Um grupo de campos (Reenquadrar, Cor, Fade...) e os tipos de item a que ele se aplica. */
export interface FilterGroup {
  id: string
  label: string
  applies: FilterTarget[]
  /** Os campos; `key` é relativo ao item (ou à `base` fixa do grupo). */
  fields: FieldDef[]
  /** Caminho fixo na spec; só os grupos do projeto têm ("output", "audio"). Os outros seguem o item selecionado. */
  base?: string
  /** A definição do schema que dá os padrões do grupo quando ele tem `base` fixa. */
  defaultsDef?: string
}

export interface FilterTargetInfo {
  /** A definição do schema (`$defs`) do item; nula no projeto, cujos grupos trazem a deles. */
  def: string | null
  title: string
}

const FIELD_KINDS: readonly FieldKind[] = ['text', 'number', 'select', 'check', 'file']

/** Um campo como está no JSON: o tipo ainda é texto livre, e a definição do schema pode vir do grupo. */
type RawField = Omit<Partial<FieldDef>, 'kind'> & { kind: string; key: string; label: string }

interface RawGroup {
  id: string
  label: string
  applies: FilterTarget[]
  def: string
  base?: string
  defaultsDef?: string
  fields: RawField[]
}

/**
 * Lê o JSON do catálogo: cada campo herda a definição do schema do grupo (quando não traz a sua) e um campo mal
 * escrito derruba a leitura na hora, em vez de sumir da tela sem aviso.
 */
export function parseFilterCatalog(raw: { groups: RawGroup[] }): FilterGroup[] {
  return raw.groups.map((group) => {
    const fields = group.fields.map((field) => {
      if (!FIELD_KINDS.includes(field.kind as FieldKind)) {
        throw new Error(`Catálogo de filtros: o campo ${group.id}/${field.key} tem o tipo desconhecido "${field.kind}".`)
      }
      return { ...field, def: field.def ?? group.def } as FieldDef
    })
    return {
      id: group.id,
      label: group.label,
      applies: group.applies,
      fields,
      ...(group.base ? { base: group.base } : {}),
      ...(group.defaultsDef ? { defaultsDef: group.defaultsDef } : {}),
    }
  })
}

export const FILTER_CATALOG: FilterGroup[] = parseFilterCatalog(catalogData as unknown as { groups: RawGroup[] })

export const FILTER_TARGETS = catalogData.targets as unknown as Record<FilterTarget, FilterTargetInfo>

/** Os grupos que valem para o tipo de item, na ordem do catálogo. */
export function groupsFor(target: FilterTarget): FilterGroup[] {
  return FILTER_CATALOG.filter((group) => group.applies.includes(target))
}

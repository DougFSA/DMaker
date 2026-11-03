/* Leitura do JSON Schema da spec (GET /api/schema): as opções de cada lista e os limites de cada número vêm
   dele, não de uma cópia escrita à mão. Assim, um valor novo no `domain/spec.py` aparece no formulário sozinho. */

type SchemaNode = Record<string, unknown>

export type FieldType = 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object' | 'unknown'

/** O que o formulário precisa saber de um campo da spec. */
export interface FieldInfo {
  type: FieldType
  /** Os valores aceitos, quando o campo é uma lista fechada (`enum`). */
  options: string[] | null
  min: number | null
  max: number | null
  /** O mínimo não vale ele mesmo (`exclusiveMinimum`): o campo precisa ser maior que isto. */
  exclusiveMin: number | null
  default: unknown
  /** O campo aceita `null` (ou seja, "usar o padrão"). */
  nullable: boolean
}

const EMPTY_INFO: FieldInfo = {
  type: 'unknown',
  options: null,
  min: null,
  max: null,
  exclusiveMin: null,
  default: undefined,
  nullable: false,
}

function asNode(value: unknown): SchemaNode | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as SchemaNode) : null
}

/** A definição `$defs.<nome>` do schema. */
export function schemaDef(schema: SchemaNode | null, name: string): SchemaNode | null {
  return asNode(asNode(schema?.$defs)?.[name])
}

/** Segue um `$ref` ("#/$defs/Nome") até a definição. */
function resolveRef(schema: SchemaNode, node: SchemaNode): SchemaNode {
  const ref = node.$ref
  if (typeof ref !== 'string') return node
  const name = ref.split('/').pop() ?? ''
  return schemaDef(schema, name) ?? node
}

/** Junta o nó e as alternativas dele (`anyOf`), separando o `null`, que só diz que o campo é opcional. */
function flatten(schema: SchemaNode, node: SchemaNode): { nodes: SchemaNode[]; nullable: boolean } {
  const alternatives = Array.isArray(node.anyOf) ? (node.anyOf as unknown[]) : [node]
  const nodes: SchemaNode[] = []
  let nullable = false
  for (const alternative of alternatives) {
    const resolved = resolveRef(schema, asNode(alternative) ?? {})
    if (resolved.type === 'null') nullable = true
    else nodes.push(resolved)
  }
  return { nodes, nullable }
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' ? value : null
}

/** Informações de `Definição.propriedade` (por exemplo `Output` e `quality`); null se o schema não a conhece. */
export function fieldInfo(schema: SchemaNode | null, defName: string, prop: string): FieldInfo | null {
  if (!schema) return null
  const property = asNode(asNode(schemaDef(schema, defName)?.properties)?.[prop])
  if (!property) return null
  const { nodes, nullable } = flatten(schema, property)
  const node = nodes[0]
  if (!node) return { ...EMPTY_INFO, nullable, default: property.default }
  const type = typeof node.type === 'string' ? (node.type as FieldType) : 'unknown'
  const options = Array.isArray(node.enum) ? (node.enum as unknown[]).map(String) : null
  return {
    type,
    options,
    min: numberOrNull(node.minimum),
    max: numberOrNull(node.maximum),
    exclusiveMin: numberOrNull(node.exclusiveMinimum),
    default: property.default,
    nullable,
  }
}

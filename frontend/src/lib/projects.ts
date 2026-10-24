import type { ProjectListItem, TemplateInfo, TemplateParamValue } from '@/api'

/** Projetos cujo nome, preset ou marca contêm o texto digitado (sem diferenciar maiúsculas e acentos). */
export function filterProjects(projects: ProjectListItem[], query: string): ProjectListItem[] {
  const needle = normalize(query)
  if (!needle) return projects
  return projects.filter((project) =>
    [project.name, project.preset ?? '', project.brand ?? ''].some((field) => normalize(field).includes(needle)),
  )
}

function normalize(text: string): string {
  return text
    .normalize('NFD')
    .replace(/\p{M}/gu, '') // tira os acentos separados pelo NFD
    .toLowerCase()
    .trim()
}

/** Valores iniciais do formulário de um template: o padrão de cada parâmetro, quando existe. */
export function defaultParamValues(template: TemplateInfo): Record<string, TemplateParamValue | undefined> {
  const values: Record<string, TemplateParamValue | undefined> = {}
  for (const [name, param] of Object.entries(template.params)) {
    values[name] = param.default ?? (param.type === 'bool' ? false : undefined)
  }
  return values
}

/** Parâmetros que seguem na requisição: vazios ficam de fora para o backend aplicar o padrão do template. */
export function buildTemplateParams(
  template: TemplateInfo,
  values: Record<string, TemplateParamValue | undefined>,
): Record<string, TemplateParamValue> {
  const params: Record<string, TemplateParamValue> = {}
  for (const name of Object.keys(template.params)) {
    const value = values[name]
    if (value === undefined || value === '') continue
    if (Array.isArray(value) && value.length === 0) continue
    params[name] = value
  }
  return params
}

/** Nomes dos parâmetros obrigatórios ainda sem valor, para avisar antes de chamar o servidor. */
export function missingRequiredParams(
  template: TemplateInfo,
  values: Record<string, TemplateParamValue | undefined>,
): string[] {
  const filled = buildTemplateParams(template, values)
  return Object.entries(template.params)
    .filter(([name, param]) => param.required && !(name in filled))
    .map(([name]) => name)
}

/** "a, b, c" digitado no campo vira ["a", "b", "c"]. */
export function parseList(text: string): string[] {
  return text
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

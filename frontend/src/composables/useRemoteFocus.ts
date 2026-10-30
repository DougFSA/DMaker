import { onScopeDispose } from 'vue'
import type { RouteLocationNormalizedLoaded, RouteLocationRaw, Router } from 'vue-router'
import { useEditorStore } from '@/stores/editor'
import { useJobsStore, type JobView } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useWorkspaceStore } from '@/stores/workspace'

/**
 * Para onde levar a pessoa quando a CLI ou o MCP dispara um job de um projeto. Quem já está na tela do projeto (ou
 * no editor dele) fica onde está, porque o andamento aparece ali sozinho; quem está no editor de outro projeto
 * continua no editor; o resto vai para a tela do projeto.
 */
export function focusTarget(
  route: Pick<RouteLocationNormalizedLoaded, 'name' | 'params'>,
  project: string,
): RouteLocationRaw | null {
  const here = route.name === 'project' || route.name === 'editor'
  if (here && route.params.name === project) return null
  return { name: route.name === 'editor' ? 'editor' : 'project', params: { name: project } }
}

/**
 * Abre sozinha o projeto do job que a CLI ou o MCP disparou, como a interface clássica fazia. Se o editor tem
 * mudanças não salvas, não tira a pessoa de lá: avisa e deixa o botão para ir quando ela quiser.
 */
export function useRemoteFocus(router: Router): void {
  const jobs = useJobsStore()
  const editor = useEditorStore()
  const workspace = useWorkspaceStore()
  const toasts = useToastsStore()

  function show(job: JobView): void {
    const project = job.project
    if (!project) return
    const target = focusTarget(router.currentRoute.value, project)
    if (!target) return
    if (editor.dirty) {
      toasts.push({
        tone: 'info',
        title: 'Um job novo começou',
        description: `${job.description}. O editor tem mudanças não salvas, então a tela não foi trocada.`,
        action: { label: 'Abrir o projeto', run: () => void router.push(target) },
      })
      return
    }
    workspace.openProject(project)
    void router.push(target)
  }

  onScopeDispose(jobs.onJobFocus(show))
}

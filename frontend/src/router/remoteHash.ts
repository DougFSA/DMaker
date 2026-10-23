import type { Router } from 'vue-router'
import { useJobsStore } from '@/stores/jobs'

export interface RemoteRenderTarget {
  project: string
  job: string | null
}

/** Um render disparado pela CLI ou pelo MCP abre a interface em `/#project=<nome>&job=<id>`
 * (ver RenderDispatcher no backend). Devolve null quando o hash não é desse formato. */
export function parseRemoteHash(hash: string): RemoteRenderTarget | null {
  const params = new URLSearchParams(hash.replace(/^#/, ''))
  const project = params.get('project')
  if (!project) return null
  return { project, job: params.get('job') }
}

/** Leva à tela do projeto e passa a acompanhar o job que a CLI/MCP iniciou. */
export async function followRemoteRender(router: Router, hash: string): Promise<boolean> {
  const target = parseRemoteHash(hash)
  if (!target) return false
  if (target.job) useJobsStore().track(target.job, { project: target.project })
  await router.replace({ name: 'project', params: { name: target.project } })
  return true
}

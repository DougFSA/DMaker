import { onScopeDispose } from 'vue'
import { api } from '@/api'

const PING_INTERVAL_MS = 5000

/** Avisa o servidor a cada 5 s enquanto a aba está visível: se alguém está olhando a interface, um render
 * disparado pela CLI ou pelo MCP não precisa abrir outra aba (ver RenderDispatcher no backend). */
export function useClientHeartbeat(): void {
  const ping = () => {
    if (document.visibilityState === 'visible') api.clients.ping().catch(() => undefined)
  }
  ping()
  const timer = setInterval(ping, PING_INTERVAL_MS)
  onScopeDispose(() => clearInterval(timer))
}

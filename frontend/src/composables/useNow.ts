import { onScopeDispose, ref, type Ref } from 'vue'

/** Relógio reativo (ms) que faz o tempo decorrido dos jobs andar sem nova chamada à API. */
export function useNow(intervalMs = 1000): Ref<number> {
  const now = ref(Date.now())
  const timer = setInterval(() => {
    now.value = Date.now()
  }, intervalMs)
  onScopeDispose(() => clearInterval(timer))
  return now
}

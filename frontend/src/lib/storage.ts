/* localStorage pode lançar (modo privado, dados bloqueados): a interface precisa funcionar sem ele. */

export function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // sem persistência: a preferência vale só até recarregar a página
  }
}

export function removeStored(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // sem acesso ao armazenamento, a preferência volta ao padrão só ao recarregar a página
  }
}

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

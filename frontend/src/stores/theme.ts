import { defineStore } from 'pinia'
import { ref } from 'vue'
import { readStored, writeStored } from '@/lib/storage'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'dmaker.theme'

function applyToDocument(theme: Theme): void {
  document.documentElement.dataset.theme = theme
}

export const useThemeStore = defineStore('theme', () => {
  // escuro é o padrão; o claro só vale se a pessoa escolheu antes
  const theme = ref<Theme>(readStored(STORAGE_KEY) === 'light' ? 'light' : 'dark')
  applyToDocument(theme.value)

  function set(next: Theme): void {
    theme.value = next
    applyToDocument(next)
    writeStored(STORAGE_KEY, next)
  }

  function toggle(): void {
    set(theme.value === 'dark' ? 'light' : 'dark')
  }

  return { theme, set, toggle }
})

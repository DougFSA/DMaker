/* Os níveis de ruído por banda que o editor já mediu, um por perfil. Moram aqui (e não no cartão do efeito) porque o
   cartão é refeito toda vez que a spec volta do servidor, e o gráfico do perfil que acabou de ser pego não pode sumir
   junto. Trocar de projeto esquece tudo: o nome "sala" de um projeto não é o de outro. */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import type { NoiseProfileReport } from '@/api'
import { useEditorStore } from './editor'

export const useNoiseProfilesStore = defineStore('noiseProfiles', () => {
  const editor = useEditorStore()
  const reports = ref<Record<string, NoiseProfileReport>>({})

  /** Guarda o nível medido de um perfil (e troca o de antes, se o perfil foi pego de novo). */
  function remember(report: NoiseProfileReport): void {
    reports.value = { ...reports.value, [report.name]: report }
  }

  watch(
    () => editor.name,
    () => {
      reports.value = {}
    },
  )

  return { reports, remember }
})

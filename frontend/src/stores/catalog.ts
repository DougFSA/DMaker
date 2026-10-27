import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type BrandInfo, type PresetInfo, type TemplateInfo } from '@/api'

/** Listas de referência que as telas só leem: presets, marcas e templates. */
export const useCatalogStore = defineStore('catalog', () => {
  const presets = ref<PresetInfo[]>([])
  const brands = ref<BrandInfo[]>([])
  const templates = ref<TemplateInfo[]>([])
  const loaded = ref(false)
  let loading: Promise<void> | null = null

  async function load(): Promise<void> {
    if (loaded.value) return
    // várias telas pedem ao mesmo tempo ao abrir: uma só ida ao servidor
    loading ??= (async () => {
      try {
        const [state, templateList] = await Promise.all([api.state(), api.templates.list()])
        presets.value = state.presets
        brands.value = state.brands
        templates.value = templateList
        loaded.value = true
      } finally {
        loading = null
      }
    })()
    await loading
  }

  return { presets, brands, templates, loaded, load }
})

<script setup lang="ts">
/* Vozes: a biblioteca (ouvir, usar, remover) e, ao lado, a criação de uma voz nova (clonar ou desenhar).
   A casca da área Voz (VoiceShellView) já traz o título e as abas. */
import { computed, onMounted, ref } from 'vue'
import { errorMessage } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import NewVoiceCard from '@/components/voice/NewVoiceCard.vue'
import VoiceLibraryCard from '@/components/voice/VoiceLibraryCard.vue'
import { brandOptions } from '@/lib/voice'
import { useCatalogStore } from '@/stores/catalog'
import { useVoiceStore } from '@/stores/voice'

const voices = useVoiceStore()
const catalog = useCatalogStore()

const optionsFailure = ref('')
const brands = computed(() => brandOptions(catalog.brands))

async function loadOptions(): Promise<void> {
  optionsFailure.value = ''
  try {
    await voices.loadOptions()
  } catch (error) {
    optionsFailure.value = errorMessage(error)
  }
}

onMounted(() => {
  void loadOptions()
  void voices.loadVoices()
  // as marcas só alimentam os seletores: se faltarem, a lista de vozes continua funcionando
  void catalog.load().catch(() => undefined)
})
</script>

<template>
  <div class="voices">
    <VoiceLibraryCard :languages="voices.options?.languages ?? []" :brands="brands" />

    <NewVoiceCard v-if="voices.options" :options="voices.options" :brands="brands" />
    <div v-else-if="optionsFailure" class="voices__failure" role="alert">
      <p>Não consegui carregar as opções de voz: {{ optionsFailure }}</p>
      <AppButton size="sm" @click="loadOptions">Tentar de novo</AppButton>
    </div>
    <p v-else class="voices__loading" role="status">Carregando as opções de voz...</p>
  </div>
</template>

<style scoped>
.voices {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}

/* a partir de 1100 px a biblioteca e a criação ficam lado a lado (a interface responde até 1280 px) */
@media (min-width: 1100px) {
  .voices {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr);
  }
}

.voices__loading {
  color: var(--color-text-soft);
}

.voices__failure {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3);
  color: var(--color-error);
}
</style>

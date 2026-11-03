<script setup lang="ts">
/* Modelos: o que está baixado em cache/models, quanto ocupa, para que serve e de que licença, com baixar, apagar e
   limpar as sobras. O servidor mede o disco e escreve o aviso de cada exclusão; a tela só mostra e pede confirmação. */
import { computed, onMounted } from 'vue'
import LeftoversCard from '@/components/models/LeftoversCard.vue'
import ModelsSummary from '@/components/models/ModelsSummary.vue'
import ModelsTable from '@/components/models/ModelsTable.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import { leftoversTotal } from '@/lib/models'
import { useModelsStore } from '@/stores/models'

const models = useModelsStore()

const blockedReason = computed(() => (models.anyDownloading ? 'Espere o download terminar para apagar as sobras.' : ''))

onMounted(() => void models.load())
</script>

<template>
  <PageHeader title="Modelos" subtitle="Os modelos de IA instalados na máquina.">
    <AppButton :loading="models.loading" @click="models.load()">Medir de novo</AppButton>
  </PageHeader>

  <div class="models">
    <p class="models__hint">
      Os modelos baixam sozinhos na primeira vez que uma função precisa deles. Aqui você vê o que ocupa o disco, a licença de
      cada um e pode baixar antes ou apagar o que não usa.
    </p>

    <div v-if="models.failure" class="models__failure" role="alert">
      <p>{{ models.failure }}</p>
      <AppButton size="sm" @click="models.load()">Tentar de novo</AppButton>
    </div>

    <p v-else-if="!models.inventory" class="models__hint" role="status">Medindo o disco...</p>

    <template v-if="models.inventory">
      <ModelsSummary :inventory="models.inventory" />

      <AppCard flush>
        <ModelsTable
          :models="models.inventory.models"
          :downloads="models.downloads"
          :busy="models.isBusy"
          @download="models.download($event)"
          @remove="models.remove($event)"
        />
      </AppCard>

      <LeftoversCard
        v-if="models.inventory.leftovers.length > 0"
        :leftovers="models.inventory.leftovers"
        :total="leftoversTotal(models.inventory)"
        :loading="models.pruning"
        :blocked-reason="blockedReason"
        @prune="models.prune()"
      />
    </template>
  </div>
</template>

<style scoped>
.models {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.models__hint {
  max-width: 48rem;
  color: var(--color-text-soft);
}

.models__failure {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-error);
}
</style>

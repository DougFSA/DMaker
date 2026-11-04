<script setup lang="ts">
/* "Bipar a seleção": o bipe de censura do painel Áudio. Silencia o trecho selecionado no item e põe um Tom de 1 kHz no mesmo
   lugar, num passo só do desfazer (a operação `censor_beep`). Entra na barra pelo ponto de extensão `AUDIO_TOOLBAR_EXTRAS`. */
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useAudioPanelStore } from '@/stores/audioPanel'

const panel = useAudioPanelStore()

const hasSelection = computed(() => panel.selection !== null && panel.selection.end > panel.selection.start)
</script>

<template>
  <AppButton
    size="sm"
    :disabled="!hasSelection || panel.busy"
    title="Silencia a seleção neste item e põe um bipe de 1 kHz no lugar (um passo só do desfazer)"
    data-audio-censor
    @click="panel.censor()"
  >
    Bipar a seleção
  </AppButton>
</template>

<script setup lang="ts">
/* "Gravar": abre a janela de gravação a partir do painel Áudio. Com um trecho de voz gravada selecionado na onda, a janela
   já vem pronta para regravá-lo (punch-in). Entra na barra pelo ponto de extensão `AUDIO_TOOLBAR_EXTRAS`. */
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useRecordingStore } from '@/stores/recording'

const recording = useRecordingStore()
const title = computed(() =>
  recording.punchCandidate
    ? 'Gravar do microfone: com o trecho selecionado, regrava só ele (punch-in) e guarda o take antigo'
    : 'Gravar do microfone numa voz gravada nova',
)
</script>

<template>
  <AppButton size="sm" :title="title" data-audio-record @click="recording.openDialog()">Gravar</AppButton>
</template>

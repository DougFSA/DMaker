<script setup lang="ts">
/* A faixa de escolha quando o projeto mudou no disco por fora (Claude, agente ou CLI) e o editor tem mudanças que
   ainda não foram salvas, ou quando o Salvar foi recusado por isso. Nada se perde em silêncio: a pessoa escolhe entre
   recarregar o que está no disco (e descartar o que não foi salvo) e manter o dela (gravando por cima). */
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()
</script>

<template>
  <div v-if="editor.conflict" class="banner" role="alert">
    <AppIcon name="alert" :size="18" />
    <div class="banner__text">
      <strong>O projeto mudou fora do editor (pelo Claude, pelo agente ou pela CLI).</strong>
      <span>
        {{
          editor.dirty
            ? 'Você tem mudanças que ainda não foram salvas. Recarregar traz a versão do disco e descarta as suas; manter as suas grava por cima da do disco.'
            : 'Escolha entre trazer a versão do disco e gravar por cima dela a que está na tela.'
        }}
      </span>
    </div>
    <div class="banner__actions">
      <AppButton size="sm" :disabled="editor.saving" @click="editor.reloadFromConflict()">Recarregar do disco</AppButton>
      <AppButton size="sm" variant="primary" :loading="editor.saving" @click="editor.keepMine()">Manter o meu</AppButton>
    </div>
  </div>
</template>

<style scoped>
.banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-warning);
  border-radius: var(--radius-md);
  background: var(--color-warning-bg);
  color: var(--color-warning);
  font-size: var(--text-sm);
}

.banner__text {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 14rem;
  overflow-wrap: anywhere;
}

.banner__text span {
  color: var(--color-text-soft);
}

.banner__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
</style>

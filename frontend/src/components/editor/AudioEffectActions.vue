<script setup lang="ts">
/* As ações de um efeito, um botão cada, desenhados pelo que o catálogo diz (`actions`): o Noise Gate tem "Analisar ruído",
   que mede um trecho em que ninguém fala e preenche o limiar. Nada aqui sabe de um efeito em particular: o botão chama a
   ação pelo nome, e os campos que ela preenche (`fills`) saem da resposta. O valor sugerido vai para a spec como uma edição
   comum (um passo do desfazer), e a pessoa ajusta depois. */
import { ref } from 'vue'
import { errorMessage, type AudioEffectAction, type AudioEffectInfo } from '@/api'
import { api } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import { effectPath, targetOfList } from '@/lib/audioEffects'
import { pruneEmpty } from '@/lib/editorPaths'
import { useEditorStore } from '@/stores/editor'

const props = defineProps<{
  info: AudioEffectInfo
  /** Onde a cadeia mora na spec (`audio.voiceover.0.effects`) e a posição do efeito nela. */
  listPath: string
  index: number
  /** O perfil de ruído do efeito, quando ele tem (a ação o usa para achar o trecho sem fala). */
  profile?: string
}>()

const editor = useEditorStore()
const running = ref('')
const message = ref('')
const problem = ref('')

async function run(action: AudioEffectAction): Promise<void> {
  const project = editor.name
  if (!project || !editor.spec) return
  running.value = action.id
  message.value = ''
  problem.value = ''
  editor.flushPendingEdits()
  try {
    const answer = await api.editor.effectAction(project, pruneEmpty(editor.spec), {
      effect: props.info.type,
      action: action.id,
      target: targetOfList(props.listPath),
      ...(props.profile ? { profile: props.profile } : {}),
    })
    for (const [field, value] of Object.entries(answer.fills)) {
      // só os campos que a ação declarou; o resto da resposta é informação
      if (action.fills.includes(field)) editor.setField(effectPath(props.listPath, props.index, field), value)
    }
    message.value = answer.message ?? 'Pronto.'
  } catch (error) {
    problem.value = errorMessage(error)
  } finally {
    running.value = ''
  }
}
</script>

<template>
  <div v-if="info.actions && info.actions.length > 0" class="actions" data-effect-actions>
    <div v-for="action in info.actions" :key="action.id" class="actions__item">
      <AppButton size="sm" :loading="running === action.id" :disabled="running !== ''" :title="action.hint" :data-effect-action="action.id" @click="run(action)">
        {{ action.label }}
      </AppButton>
    </div>
    <p v-if="message" class="actions__note" role="status" data-effect-action-message>{{ message }}</p>
    <p v-if="problem" class="actions__note actions__note--error" role="alert" data-effect-action-error>{{ problem }}</p>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
}

.actions__note {
  flex: 1 1 100%;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.actions__note--error {
  color: var(--color-danger);
}
</style>

<script setup lang="ts">
/* "Usar no projeto": troca o arquivo original pelo novo (a fala corrigida, a voz trocada) em tudo que o projeto usa e
   salva. Só vale para arquivo que veio de um projeto; para um arquivo enviado do computador não há o que trocar. */
import { computed, ref, watch } from 'vue'
import { errorMessage } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import type { MediaEntry } from '@/lib/media'
import { useSourceReplacementStore } from '@/stores/sourceReplacement'
import { useToastsStore } from '@/stores/toasts'

const props = withDefaults(
  defineProps<{
    /** O projeto de onde veio o arquivo. */
    project: string | null
    /** A entrada da spec que será trocada; vazia quando o arquivo foi enviado. */
    entry: MediaEntry | null
    /** O arquivo novo, no caminho do servidor. */
    newPath: string
    /** O que foi feito ao arquivo, para a mensagem final ("arquivo corrigido", "voz trocada"). */
    what: string
    /** Quando o resultado não pode entrar no projeto (a troca de voz de só um trecho), o motivo. */
    blockedReason?: string
  }>(),
  { blockedReason: '' },
)

const emit = defineEmits<{ used: [points: number] }>()

const replacement = useSourceReplacementStore()
const toasts = useToastsStore()
const message = ref('')
/** O arquivo já entrou no projeto: usar de novo não acharia mais o original lá. */
const used = ref(false)

const blocker = computed(() => {
  if (props.blockedReason) return props.blockedReason
  if (!props.project || !props.entry) return 'Para usar no projeto, escolha um arquivo do projeto aberto.'
  return ''
})

// um resultado novo é outro arquivo, e o botão volta a valer
watch(
  () => props.newPath,
  () => {
    used.value = false
    message.value = ''
  },
)

async function use(): Promise<void> {
  const { project, entry } = props
  if (blocker.value || used.value || !project || !entry) return
  message.value = ''
  try {
    const points = await replacement.replace(project, entry, props.newPath)
    if (points === 0) {
      message.value = 'Nenhum trecho do projeto usa este arquivo.'
      toasts.push({ tone: 'error', title: 'Nada foi trocado', description: message.value })
      return
    }
    message.value = `Projeto ${project} atualizado: ${props.what} em ${points} ponto(s).`
    toasts.push({ tone: 'success', title: 'Projeto atualizado', description: message.value })
    used.value = true
    emit('used', points)
  } catch (failure) {
    message.value = `Não consegui usar no projeto: ${errorMessage(failure)}`
    toasts.push({ tone: 'error', title: 'Não consegui usar no projeto', description: errorMessage(failure) })
  }
}
</script>

<template>
  <div class="use">
    <AppButton
      variant="primary"
      :disabled="!!blocker || used"
      :loading="replacement.busy"
      title="Troca o arquivo original pelo novo nos trechos do projeto e salva"
      @click="use"
    >
      Usar no projeto
    </AppButton>
    <p v-if="blocker" class="use__note">{{ blocker }}</p>
    <p v-else-if="message" class="use__note" role="status">{{ message }}</p>
  </div>
</template>

<style scoped>
.use {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
}

.use__note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  overflow-wrap: anywhere;
}
</style>

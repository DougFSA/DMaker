<script setup lang="ts">
/* Botão de baixar. Com `url`, baixa na hora; com `resolve`, primeiro espera o endereço (o .zip das trilhas só
   existe depois de um job) e então baixa. Nos dois casos o download sai por link programático, sem sair da página. */
import { ref } from 'vue'
import { errorMessage } from '@/api'
import { triggerDownload } from '@/lib/files'
import { useToastsStore } from '@/stores/toasts'
import AppButton, { type ButtonVariant } from './AppButton.vue'
import AppIcon from './AppIcon.vue'

const props = withDefaults(
  defineProps<{
    /** Endereço já conhecido do arquivo. */
    url?: string
    /** Produz o endereço na hora do clique (roda um job, por exemplo). Tem prioridade sobre `url`. */
    resolve?: () => Promise<string>
    /** Nome do arquivo salvo; vazio deixa o servidor ou o navegador escolher. */
    filename?: string
    label?: string
    size?: 'sm' | 'md'
    variant?: ButtonVariant
    disabled?: boolean
  }>(),
  { label: 'Baixar', size: 'md', variant: 'secondary' },
)

const emit = defineEmits<{ downloaded: [url: string] }>()
const toasts = useToastsStore()
const working = ref(false)

async function start(): Promise<void> {
  working.value = true
  try {
    const target = props.resolve ? await props.resolve() : props.url
    if (!target) return
    triggerDownload(target, props.filename)
    emit('downloaded', target)
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não consegui baixar o arquivo', description: errorMessage(error) })
  } finally {
    working.value = false
  }
}
</script>

<template>
  <AppButton
    :variant="variant"
    :size="size"
    :loading="working"
    :disabled="disabled || (!url && !resolve)"
    @click="start"
  >
    <AppIcon name="download" :size="size === 'sm' ? 14 : 18" />
    {{ label }}
  </AppButton>
</template>
